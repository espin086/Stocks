"""Missing data has a policy, never a default.

A missing date is one of: the market was closed, the instrument was not yet
listed, it has been delisted, or the provider has a gap. Only a provider gap is
eligible for filling, and the caller must say ``drop``, ``ffill`` or ``raise``.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from sobres.core.errors import InsufficientDataError

GapKind = Literal["market_closed", "not_listed", "delisted", "provider_gap"]
FillPolicy = Literal["drop", "ffill", "raise"]
FILL_POLICIES: tuple[str, ...] = ("drop", "ffill", "raise")


def classify_gaps(frame: pd.DataFrame, calendar: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Classify every ``NaN`` in ``frame``.

    ``calendar`` is the set of trading days (defaults to the union of dates in
    the frame). A date outside the calendar is ``market_closed``; before a
    column's first observation, ``not_listed``; after its last, ``delisted``;
    otherwise a ``provider_gap``. Returns a frame of the same shape with a
    string kind where the input was ``NaN`` and ``None`` elsewhere.
    """
    cal = calendar if calendar is not None else pd.DatetimeIndex(frame.index)
    kinds = pd.DataFrame(None, index=frame.index, columns=frame.columns, dtype=object)
    for column in frame.columns:
        series = frame[column]
        valid = series.dropna()
        first = valid.index.min() if len(valid) else None
        last = valid.index.max() if len(valid) else None
        for when in series.index[series.isna()]:
            if when not in cal:
                kinds.loc[when, column] = "market_closed"
            elif first is None or when < first:
                kinds.loc[when, column] = "not_listed"
            elif last is not None and when > last:
                kinds.loc[when, column] = "delisted"
            else:
                kinds.loc[when, column] = "provider_gap"
    return kinds


def apply_fill_policy(frame: pd.DataFrame, policy: FillPolicy) -> pd.DataFrame:
    """Handle provider gaps under an explicit policy. No default.

    Only provider gaps are touched: ``ffill`` carries the prior observation
    across them, ``drop`` removes rows that contain one, ``raise`` refuses.
    Listing and delisting gaps are left as ``NaN`` for alignment to resolve.
    ``attrs["filled"]`` records how many observations were filled or dropped.
    """
    if policy not in FILL_POLICIES:
        raise ValueError(f"fill policy must be one of {FILL_POLICIES}, got {policy!r}")
    kinds = classify_gaps(frame)
    is_gap = kinds == "provider_gap"
    n_gaps = int(is_gap.to_numpy().sum())
    out = frame.copy()
    out.attrs = dict(frame.attrs)
    if n_gaps == 0:
        out.attrs["filled"] = {"policy": policy, "filled": 0, "dropped_rows": 0}
        return out
    if policy == "raise":
        col = str(is_gap.any().idxmax())
        when = is_gap.index[is_gap[col]][0]
        raise InsufficientDataError(
            f"{n_gaps} provider gap(s) in the data, first at {col} on {when.date()}",
            hint="choose --fill ffill or --fill drop, or --refresh to re-fetch",
        )
    if policy == "ffill":
        filled = out.ffill()
        out = out.where(~is_gap, filled)
        out.attrs["filled"] = {"policy": policy, "filled": n_gaps, "dropped_rows": 0}
        return out
    keep = ~is_gap.any(axis=1)
    dropped = int((~keep).sum())
    out = out[keep]
    out.attrs["filled"] = {"policy": policy, "filled": 0, "dropped_rows": dropped}
    return out
