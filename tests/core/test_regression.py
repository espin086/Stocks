"""OLS with robust inference: closed forms, hand-computed VIF, statsmodels as the oracle.

Scenarios: Robust standard errors; Multicollinearity; Diagnostics reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.regression import ROBUST_KINDS, VIF_FLAG, regress, vif_table

pytest.importorskip("statsmodels")
N = 200
INDEX = pd.bdate_range("2020-01-01", periods=N)


def _data(seed: int = 0, rho: float = 0.0) -> tuple[pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(0, 1, N)
    x2 = rho * x1 + np.sqrt(1 - rho**2) * rng.normal(0, 1, N)
    y = 0.5 + 2.0 * x1 - 1.0 * x2 + rng.normal(0, 0.5, N)
    return pd.Series(y, index=INDEX, name="y"), pd.DataFrame({"x1": x1, "x2": x2}, index=INDEX)


def test_coefficients_match_the_normal_equations_and_every_robust_kind_is_named() -> None:
    y, x = _data()
    design = np.column_stack([np.ones(N), x.to_numpy()])
    beta = np.linalg.solve(design.T @ design, design.T @ y.to_numpy())
    for kind in ROBUST_KINDS:
        fit = regress(y, x, robust=kind)
        assert fit.robust == kind
        assert [fit.terms[k].coefficient for k in ("const", "x1", "x2")] == pytest.approx(beta)
        assert fit.n_obs == N and (fit.hac_lags is not None) == (kind == "hac")
    assert regress(y, x, robust="hac", hac_lags=3).hac_lags == 3
    assert regress(y, x, robust="hac").hac_lags == int(np.floor(4 * (N / 100) ** (2 / 9)))
    with pytest.raises(UsageError):
        regress(y, x, robust="bootstrap")


def test_robust_standard_errors_match_statsmodels() -> None:
    sm = pytest.importorskip("statsmodels.api")
    y, x = _data(seed=3)
    design = sm.add_constant(x.to_numpy())
    for kind, kwargs in (
        ("none", {}),
        ("hc3", {"cov_type": "HC3"}),
        ("hac", {"cov_type": "HAC", "cov_kwds": {"maxlags": 5}}),
    ):
        ref = sm.OLS(y.to_numpy(), design).fit(**kwargs)
        fit = regress(y, x, robust=kind, hac_lags=5)
        for i, name in enumerate(("const", "x1", "x2")):
            assert fit.terms[name].se == pytest.approx(ref.bse[i], rel=1e-9)
            assert fit.terms[name].p == pytest.approx(ref.pvalues[i], rel=1e-6)


def test_multicollinearity_vif_matches_the_hand_formula() -> None:
    # Two regressors with correlation ρ: VIF = 1 / (1 − ρ²) for both (the single-regressor
    # auxiliary R² is ρ²). ρ = 0.95 ⇒ VIF ≈ 10.26, above the flag.
    y, x = _data(seed=1, rho=0.95)
    rho = float(np.corrcoef(x["x1"], x["x2"])[0, 1])
    vif = vif_table(x)
    assert vif["x1"] == pytest.approx(1 / (1 - rho**2)) and vif["x2"] == pytest.approx(vif["x1"])
    fit = regress(y, x)
    assert fit.vif == vif and VIF_FLAG == 10.0
    assert fit.vif_flags == ["x1", "x2"] if vif["x1"] > 10 else fit.vif_flags == []
    loose = regress(*_data(seed=1, rho=0.0))
    assert loose.vif_flags == [] and all(v < 1.2 for v in loose.vif.values())
    single = regress(y, x[["x1"]])
    assert single.vif == {"x1": 1.0}


def test_diagnostics_reported() -> None:
    y, x = _data(seed=2)
    fit = regress(y, x, robust="none")
    assert 0.9 < fit.r2 < 1.0 and fit.adj_r2 < fit.r2
    assert fit.f_statistic > 100 and fit.f_pvalue < 1e-6
    assert 1.6 < fit.durbin_watson < 2.4  # independent residuals sit near 2
    assert 0.0 <= fit.breusch_pagan_pvalue <= 1.0 and not fit.heteroskedastic
    rng = np.random.default_rng(9)
    spread = 0.1 + 2 * (x["x1"] - x["x1"].min())  # residual variance rising with x1
    hetero = pd.Series(0.5 + 2 * x["x1"] + rng.normal(0, spread, N), index=INDEX)
    assert regress(hetero, x[["x1"]]).heteroskedastic
    with pytest.raises(InsufficientDataError):
        regress(y.iloc[:20], x.iloc[:20])
