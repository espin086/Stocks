"""Conventions settled once: annualization periods and frequency names.

No literal periods-per-year (``252``, ``52``, ``12``) may appear in
annualization code anywhere else; ``tests/architecture/`` fails on one.

Source: the 252-trading-day year is the NYSE convention (Hull, *Options,
Futures, and Other Derivatives*, ch. 15 uses 252 for volatility scaling).
"""

from __future__ import annotations

from typing import Literal

Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]

PERIODS_PER_YEAR: dict[str, int] = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}

FREQUENCIES: tuple[str, ...] = tuple(PERIODS_PER_YEAR)
