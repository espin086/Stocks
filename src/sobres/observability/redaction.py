"""Redaction at the formatter, never at call sites.

Keys matching key/token/secret/password/authorization are replaced with a
marker; credentials inside URLs (``user:pass@host`` and ``api_key=...`` query
parameters) are stripped. Applied to log records and span attributes alike.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY = re.compile(r"(key|token|secret|password|passwd|authorization)", re.IGNORECASE)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/@\s:]+)(:[^/@\s]*)?@")
_QUERY_SECRET = re.compile(
    r"(?P<name>(?:api_?key|token|secret|password|access_?token|auth))=(?P<value>[^&\s\"']+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")


def scrub_text(text: str) -> str:
    """Strip credentials embedded in free text: URL userinfo, secret query params."""
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", text)
    text = _QUERY_SECRET.sub(lambda m: f"{m.group('name')}={REDACTED}", text)
    return _BEARER.sub(lambda m: f"{m.group(1)}{REDACTED}", text)


def scrub_value(key: str | None, value: Any) -> Any:
    """Redact one value given the key it is stored under."""
    if key is not None and SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {str(k): scrub_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(scrub_value(None, v) for v in value)
    if isinstance(value, BaseException):
        return type(value)(*(scrub_value(None, a) for a in value.args))
    return value


def scrub_mapping(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): scrub_value(str(k), v) for k, v in event.items()}


def redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: scrub every key and value before rendering."""
    return scrub_mapping(event_dict)
