"""OLS with robust inference and the diagnostics that say whether to believe it.

    y = X b + e,  b = (X'X)^-1 X'y
    Standard errors: classical, HC0-HC3 (White 1980; MacKinnon & White 1985) or
    HAC (Newey & West 1987) — the kind used is always named
    VIF_j = 1 / (1 - R_j²) from regressing x_j on the other regressors (> 10 flagged)
    Durbin-Watson (1950) on residuals; Breusch-Pagan (1979) for heteroskedasticity;
    the F test of all slopes jointly zero

``statsmodels`` does the fitting and is imported lazily: the base install can
import this module, and a call without the econ extra fails with the install hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.timeseries import require_econ

Robust = Literal["hac", "hc0", "hc1", "hc2", "hc3", "none"]
ROBUST_KINDS: tuple[str, ...] = ("hac", "hc0", "hc1", "hc2", "hc3", "none")
VIF_FLAG = 10.0
MIN_OBS_PER_REGRESSOR = 10


@dataclass(frozen=True)
class Term:
    coefficient: float
    se: float
    t: float
    p: float

    def as_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Regression:
    robust: str
    hac_lags: int | None
    n_obs: int
    terms: dict[str, Term]
    """``const`` first, then every regressor in the order supplied."""
    r2: float
    adj_r2: float
    f_statistic: float
    f_pvalue: float
    durbin_watson: float
    breusch_pagan_statistic: float
    breusch_pagan_pvalue: float
    vif: dict[str, float]

    @property
    def vif_flags(self) -> list[str]:
        return [name for name, value in self.vif.items() if value > VIF_FLAG]

    @property
    def heteroskedastic(self) -> bool:
        return self.breusch_pagan_pvalue < 0.05


def vif_table(x: pd.DataFrame) -> dict[str, float]:
    """Variance inflation factor per column; a single regressor has VIF 1 by definition."""
    if x.shape[1] < 2:
        return {str(c): 1.0 for c in x.columns}
    out: dict[str, float] = {}
    values = x.to_numpy(dtype="float64")
    for j, name in enumerate(x.columns):
        others = np.column_stack([np.ones(len(values)), np.delete(values, j, axis=1)])
        beta = np.linalg.lstsq(others, values[:, j], rcond=None)[0]
        resid = values[:, j] - others @ beta
        tss = float(((values[:, j] - values[:, j].mean()) ** 2).sum())
        r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else 0.0
        out[str(name)] = float("inf") if r2 >= 1.0 else 1.0 / (1.0 - r2)
    return out


def regress(
    y: pd.Series,
    x: pd.DataFrame,
    *,
    robust: Robust | str = "hac",
    hac_lags: int | None = None,
) -> Regression:
    """OLS of ``y`` on ``x`` (a constant is added) with the named covariance estimator."""
    require_econ()
    import statsmodels.api as sm
    from statsmodels.stats.diagnostic import het_breuschpagan
    from statsmodels.stats.stattools import durbin_watson

    if robust not in ROBUST_KINDS:
        raise UsageError(f"--robust must be one of {', '.join(ROBUST_KINDS)}, got {robust!r}")
    frame = pd.concat([pd.Series(y).rename("__y__"), x], axis=1, join="inner").dropna()
    n, k = len(frame), x.shape[1]
    if n < MIN_OBS_PER_REGRESSOR * (k + 1):
        raise InsufficientDataError(
            f"{n} aligned observations for {k} regressor(s); at least "
            f"{MIN_OBS_PER_REGRESSOR * (k + 1)} are needed",
            hint="widen --start/--end or drop a regressor",
        )
    design = sm.add_constant(frame[list(x.columns)].to_numpy(dtype="float64"), has_constant="add")
    target = frame["__y__"].to_numpy(dtype="float64")
    lags: int | None = None
    kwargs: dict[str, Any] = {}
    if robust == "hac":
        lags = (
            int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))) if hac_lags is None else int(hac_lags)
        )
        kwargs = {"cov_type": "HAC", "cov_kwds": {"maxlags": lags}}
    elif robust != "none":
        kwargs = {"cov_type": robust.upper()}
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # rank warnings are reported through VIF, not stderr
        fit = sm.OLS(target, design).fit(**kwargs)
    names = ["const", *[str(c) for c in x.columns]]
    terms = {
        name: Term(
            float(fit.params[i]), float(fit.bse[i]), float(fit.tvalues[i]), float(fit.pvalues[i])
        )
        for i, name in enumerate(names)
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bp_stat, bp_p, _, _ = het_breuschpagan(fit.resid, design)
    return Regression(
        robust=robust,
        hac_lags=lags,
        n_obs=n,
        terms=terms,
        r2=float(fit.rsquared),
        adj_r2=float(fit.rsquared_adj),
        f_statistic=float(fit.fvalue),
        f_pvalue=float(fit.f_pvalue),
        durbin_watson=float(durbin_watson(fit.resid)),
        breusch_pagan_statistic=float(bp_stat),
        breusch_pagan_pvalue=float(bp_p),
        vif=vif_table(frame[list(x.columns)]),
    )
