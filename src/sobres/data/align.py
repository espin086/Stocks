"""``align_frames``: the one sanctioned way to combine series from different sources.

Alignment is explicit and records what it dropped, so a shortened window is
visible in ``attrs["alignment"]`` rather than silently accepted.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from sobres.core.errors import AlignmentError, InsufficientDataError
from sobres.data.base import canonical_frame

How = Literal["inner", "outer"]


def align_frames(*frames: pd.DataFrame, how: How = "inner", min_rows: int = 1) -> pd.DataFrame:
    """Join frames on their date index.

    ``how="inner"`` keeps only dates present in every frame and raises
    ``AlignmentError`` on an empty overlap; ``how="outer"`` keeps every date.
    Each input's index is normalized to tz-naive dates first. The result's
    ``attrs["alignment"]`` records, per source, how many rows it lost.
    """
    if not frames:
        raise ValueError("align_frames needs at least one frame")
    prepared = []
    for i, frame in enumerate(frames):
        out = frame.copy()
        index = pd.DatetimeIndex(out.index)
        if index.tz is not None:
            index = index.tz_localize(None)
        out.index = index.normalize()
        out.index.name = "date"
        out = out[~out.index.duplicated(keep="last")].sort_index()
        prepared.append((str(frame.attrs.get("provider", f"source{i + 1}")), out))
    joined = pd.concat([f for _, f in prepared], axis=1, join=how)
    joined.index.name = "date"
    dropped = {name: int(len(f) - len(joined)) if how == "inner" else 0 for name, f in prepared}
    if how == "inner" and joined.empty:
        spans = "; ".join(
            f"{name}: {f.index.min().date()}→{f.index.max().date()}" if len(f) else f"{name}: empty"
            for name, f in prepared
        )
        raise AlignmentError(
            "no dates are shared by every source",
            hint=f"windows were {spans}; widen --start/--end or check the frequencies",
        )
    if len(joined) < min_rows:
        constraining = max(dropped, key=lambda k: dropped[k])
        raise InsufficientDataError(
            f"{len(joined)} aligned observations remain but {min_rows} are required",
            hint=f"the window was constrained most by {constraining}; widen --start/--end",
        )
    joined.attrs = {}
    for _, f in prepared:
        for key, value in f.attrs.items():
            joined.attrs.setdefault(key, value)
    joined.attrs["alignment"] = {"how": how, "rows": len(joined), "dropped": dropped}
    return canonical_frame(joined) if joined.dtypes.eq("float64").all() else joined
