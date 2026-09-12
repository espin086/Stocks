"""Deployment token: generated, stored hashed, compared in constant time.

A loopback-only server needs no token — the socket is unreachable remotely.
Any other bind address requires one. Tokens are 32 random bytes (256 bits of
entropy) as base64url; only a salted PBKDF2 hash is stored, in the key/value
store, and comparison is constant-time. Presented as a bearer header or an
httpOnly cookie, never in a query string.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import Counter, defaultdict, deque
from typing import Any

from sobres.core.errors import UsageError
from sobres.data.storage.base import KeyValueStore

KV_KEY = "auth.token"
COOKIE_NAME = "sobres_token"
MIN_TOKEN_BITS = 128
PBKDF2_ROUNDS = 100_000
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS or host.startswith("127.")


def generate_token() -> str:
    """32 random bytes from the OS CSPRNG, base64url without padding."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def _entropy_bits(token: str) -> float:
    """Shannon entropy of the characters times the length: a floor on strength."""
    if not token:
        return 0.0
    counts = Counter(token)
    n = len(token)
    per_char = -sum(c / n * math.log2(c / n) for c in counts.values())
    return per_char * n


def validate_strength(token: str) -> None:
    """Reject a weak user-supplied token; the tool prefers to generate its own."""
    if len(token) < 22 or _entropy_bits(token) < MIN_TOKEN_BITS:
        raise UsageError(
            "that token is too weak (it needs at least 128 bits of entropy)",
            hint="let sobres generate one: sobres serve token rotate",
        )


def hash_token(token: str, salt: bytes | None = None) -> dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, PBKDF2_ROUNDS)
    return {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(digest).decode()}


def verify_token(token: str, stored: dict[str, Any] | None) -> bool:
    if not stored or not token:
        return False
    salt = base64.b64decode(stored["salt"])
    expected = base64.b64decode(stored["hash"])
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(digest, expected)


def stored_token(kv: KeyValueStore) -> dict[str, Any] | None:
    value = kv.get(KV_KEY)
    return dict(value) if isinstance(value, dict) else None


def ensure_token(kv: KeyValueStore) -> str | None:
    """Store a generated token if none exists; return the plaintext only when new."""
    if stored_token(kv) is not None:
        return None
    token = generate_token()
    kv.set(KV_KEY, hash_token(token))
    return token


def rotate_token(kv: KeyValueStore, token: str | None = None) -> str:
    """Replace the stored token (generated unless supplied and strong enough)."""
    if token is not None:
        validate_strength(token)
    else:
        token = generate_token()
    kv.set(KV_KEY, hash_token(token))
    return token


class RateLimiter:
    """Per-source sliding window for authentication attempts."""

    def __init__(self, limit: int = 10, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, source: str, now: float | None = None) -> bool:
        stamp = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[source]
            while hits and hits[0] <= stamp - self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(stamp)
            return True
