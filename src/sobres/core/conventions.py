"""Conventions settled once: annualization periods and frequency names.

No literal periods-per-year (``252``, ``52``, ``12``) may appear in
annualization code anywhere else; ``tests/architecture/`` fails on one.

Source: the 252-trading-day year is the NYSE convention (Hull, *Options,
Futures, and Other Derivatives*, ch. 15 uses 252 for volatility scaling).
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]

PERIODS_PER_YEAR: dict[str, int] = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}

FREQUENCIES: tuple[str, ...] = tuple(PERIODS_PER_YEAR)

# Median spacing in calendar days that identifies each frequency. Daily bars
# skip weekends and holidays, so their median gap is 1 with a tolerance up to 3.
_MEDIAN_DAYS: tuple[tuple[float, str], ...] = (
    (3.5, "daily"),
    (10.0, "weekly"),
    (45.0, "monthly"),
    (135.0, "quarterly"),
    (float("inf"), "annual"),
)


def infer_frequency(index: pd.DatetimeIndex) -> Frequency:
    """Name the observation frequency of a date index from its median spacing.

    Raises ``ValueError`` on fewer than three observations, where no spacing
    is defined well enough to trust.
    """
    if len(index) < 3:
        raise ValueError("frequency inference needs at least three observations")
    gaps = pd.Series(index).diff().dropna().dt.days
    median = float(gaps.median())
    for bound, name in _MEDIAN_DAYS:
        if median <= bound:
            return name  # type: ignore[return-value]
    raise AssertionError("unreachable")  # pragma: no cover


def periods_per_year(frequency: str) -> int:
    try:
        return PERIODS_PER_YEAR[frequency]
    except KeyError:
        raise ValueError(f"unknown frequency {frequency!r}; use one of {FREQUENCIES}") from None
