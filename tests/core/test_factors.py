"""Factor regressions against closed forms and an independent implementation.

Scenarios: Supported models; Excess returns, not raw; Reported statistics;
Robust standard errors; Alpha is reported honestly; Minimum sample; Rolling betas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.factors import (
    ALPHA_NOT_DISTINGUISHABLE,
    MIN_OBS,
    MODELS,
    capm_beta,
    excess_returns,
    factor_regression,
    newey_west_lags,
    rolling_loadings,
    to_monthly_returns,
)

MONTHS = pd.date_range("2015-01-31", periods=144, freq="ME")


def _factors(n: int = 60, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "Mkt-RF": rng.normal(0.006, 0.04, n),
            "SMB": rng.normal(0.001, 0.02, n),
            "HML": rng.normal(0.000, 0.02, n),
            "RMW": rng.normal(0.002, 0.015, n),
            "CMA": rng.normal(0.001, 0.012, n),
            "MOM": rng.normal(0.004, 0.03, n),
            "RF": np.full(n, 0.001),
        },
        index=MONTHS[:n],
    )
    frame.index.name = "date"
    return frame


def test_supported_models_and_the_columns_each_uses() -> None:
    assert MODELS == ("capm", "ff3", "ff5", "ff5+mom")
    f = _factors()
    r = f["RF"] + 0.001 + 1.2 * f["Mkt-RF"]
    for model, n_terms in (("capm", 1), ("ff3", 3), ("ff5", 5), ("ff5+mom", 6)):
        fit = factor_regression(r, f, model)
        assert list(fit.loadings) == list(f.columns[:n_terms]) and fit.model == model
    with pytest.raises(UsageError):
        factor_regression(r, f, "ff7")


def test_excess_returns_subtract_the_factor_files_rf_not_a_separate_rate() -> None:
    f = _factors()
    r = pd.Series(0.01, index=f.index)
    ex = excess_returns(r, f)
    np.testing.assert_allclose(ex.to_numpy(), 0.009)  # 0.01 - RF 0.001
    with pytest.raises(UsageError):
        excess_returns(r, f.drop(columns="RF"))
    # An exact linear relation in excess terms is recovered only if RF was subtracted.
    exact = f["RF"] + 0.002 + 0.8 * f["Mkt-RF"] - 0.3 * f["SMB"] + 0.5 * f["HML"]
    fit = factor_regression(exact, f, "ff3")
    assert fit.alpha.coefficient == pytest.approx(0.002, abs=1e-12)
    assert fit.loadings["Mkt-RF"].coefficient == pytest.approx(0.8, abs=1e-12)
    assert fit.loadings["SMB"].coefficient == pytest.approx(-0.3, abs=1e-12)
    assert fit.loadings["HML"].coefficient == pytest.approx(0.5, abs=1e-12)
    assert fit.r2 == pytest.approx(1.0, abs=1e-12)


def test_reported_statistics_match_the_two_variable_closed_form() -> None:
    # Five points, one factor: y = a + b x + e. Closed form (any statistics textbook):
    # b = Sxy/Sxx, a = ȳ - b x̄, s² = Σe²/(n-2), se(b) = s/√Sxx, se(a) = s √(1/n + x̄²/Sxx).
    x = np.array([-0.02, -0.01, 0.00, 0.01, 0.03])
    y = np.array([-0.030, -0.005, 0.004, 0.012, 0.040])
    f = pd.DataFrame({"Mkt-RF": x, "RF": 0.0}, index=MONTHS[:5])
    r = pd.Series(y, index=MONTHS[:5])
    sxx = ((x - x.mean()) ** 2).sum()
    b = ((x - x.mean()) * (y - y.mean())).sum() / sxx
    a = y.mean() - b * x.mean()
    e = y - a - b * x
    s2 = (e**2).sum() / 3
    fit = factor_regression(r, f, "capm", min_obs=5, hac_lags=0)
    assert fit.loadings["Mkt-RF"].coefficient == pytest.approx(b)
    assert fit.alpha.coefficient == pytest.approx(a)
    assert fit.loadings["Mkt-RF"].se == pytest.approx(np.sqrt(s2 / sxx))
    assert fit.alpha.se == pytest.approx(np.sqrt(s2 * (1 / 5 + x.mean() ** 2 / sxx)))
    assert fit.loadings["Mkt-RF"].t == pytest.approx(b / np.sqrt(s2 / sxx))
    assert fit.r2 == pytest.approx(1 - (e**2).sum() / ((y - y.mean()) ** 2).sum())
    assert fit.adj_r2 == pytest.approx(1 - (1 - fit.r2) * 4 / 3)
    assert fit.n_obs == 5 and fit.start == MONTHS[0] and fit.end == MONTHS[4]
    assert fit.annualized_alpha == pytest.approx((1 + a) ** PERIODS_PER_YEAR["monthly"] - 1)
    for stats in (fit.alpha, *fit.loadings.values()):
        assert 0.0 <= stats.p <= 1.0 and 0.0 <= stats.p_hac <= 1.0
    assert fit.hac_lags == 0 and fit.alpha.se_hac > 0


def test_robust_standard_errors_match_statsmodels_newey_west() -> None:
    sm = pytest.importorskip("statsmodels.api")
    f = _factors(120)
    rng = np.random.default_rng(7)
    noise = np.zeros(120)
    for t in range(1, 120):  # AR(1) residuals: exactly the case HAC exists for
        noise[t] = 0.6 * noise[t - 1] + rng.normal(0, 0.02)
    r = f["RF"] + 0.003 + 1.1 * f["Mkt-RF"] + 0.4 * f["SMB"] + noise
    fit = factor_regression(r, f, "ff3", hac_lags=4)
    x = sm.add_constant(f[["Mkt-RF", "SMB", "HML"]].to_numpy())
    ref = sm.OLS((r - f["RF"]).to_numpy(), x).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    assert fit.hac_lags == 4
    assert fit.alpha.se_hac == pytest.approx(ref.bse[0], rel=1e-9)
    for i, name in enumerate(("Mkt-RF", "SMB", "HML"), start=1):
        assert fit.loadings[name].se_hac == pytest.approx(ref.bse[i], rel=1e-9)
        assert fit.loadings[name].coefficient == pytest.approx(ref.params[i], rel=1e-12)
    plain = sm.OLS((r - f["RF"]).to_numpy(), x).fit()
    assert fit.loadings["Mkt-RF"].se == pytest.approx(plain.bse[1], rel=1e-12)
    assert fit.loadings["Mkt-RF"].se_hac != pytest.approx(
        fit.loadings["Mkt-RF"].se, rel=1e-3
    )  # AR(1) residuals: HAC must differ from OLS by more than rounding
    assert newey_west_lags(120) == int(np.floor(4 * (1.2) ** (2 / 9)))  # the 1994 rule
    assert factor_regression(r, f, "ff3").hac_lags == newey_west_lags(120)


def test_alpha_is_reported_honestly() -> None:
    f = _factors(120, seed=3)
    rng = np.random.default_rng(11)
    faint = f["RF"] + 0.0002 + 1.0 * f["Mkt-RF"] + rng.normal(0, 0.03, 120)
    fit = factor_regression(faint, f, "capm")
    assert fit.alpha.p_hac > 0.05 and not fit.alpha_significant
    assert fit.alpha_statement.startswith(ALPHA_NOT_DISTINGUISHABLE)
    assert "should not be read on its own" in fit.alpha_statement
    loud = f["RF"] + 0.02 + 1.0 * f["Mkt-RF"] + rng.normal(0, 0.005, 120)
    fit = factor_regression(loud, f, "capm")
    assert fit.alpha.p_hac <= 0.05 and fit.alpha_significant
    assert "distinguishable from zero" in fit.alpha_statement
    assert ALPHA_NOT_DISTINGUISHABLE not in fit.alpha_statement


def test_minimum_sample_names_available_and_required() -> None:
    assert MIN_OBS == {"monthly": 36, "daily": 252}
    f = _factors(35)
    r = f["RF"] + f["Mkt-RF"]
    with pytest.raises(InsufficientDataError) as exc:
        factor_regression(r, f, "capm")
    assert "35 monthly observations available, 36 required" in str(exc.value)
    assert exc.value.exit_code == 5
    days = pd.bdate_range("2024-01-01", periods=100)
    fd = pd.DataFrame({"Mkt-RF": np.linspace(-0.01, 0.01, 100), "RF": 0.0}, index=days)
    with pytest.raises(InsufficientDataError, match="100 daily observations available, 252"):
        factor_regression(pd.Series(fd["Mkt-RF"]), fd, "capm", frequency="daily")


def test_rolling_betas_recover_a_loading_that_changes_halfway() -> None:
    f = _factors(72)
    beta = np.where(np.arange(72) < 36, 0.5, 1.5)
    r = f["RF"] + 0.001 + beta * f["Mkt-RF"]
    frame = rolling_loadings(r, f, "capm", window=36)
    assert list(frame.columns) == ["alpha", "Mkt-RF"] and len(frame) == 72 - 36 + 1
    assert frame["Mkt-RF"].iloc[0] == pytest.approx(0.5, abs=1e-10)  # first window: all 0.5
    assert frame["Mkt-RF"].iloc[-1] == pytest.approx(1.5, abs=1e-10)  # last window: all 1.5
    assert 0.5 < frame["Mkt-RF"].iloc[18] < 1.5  # the mixed windows show the instability
    assert frame.attrs == {"model": "capm", "window": 36, "frequency": "monthly"}
    with pytest.raises(InsufficientDataError):
        rolling_loadings(r, f, "capm", window=100)
    with pytest.raises(UsageError):
        rolling_loadings(r, f, "ff5", window=6)


def test_capm_beta_and_monthly_resampling() -> None:
    f = _factors()
    r = f["RF"] + 1.3 * f["Mkt-RF"]
    assert capm_beta(r, f) == pytest.approx(1.3, abs=1e-12)
    days = pd.bdate_range("2020-01-01", "2020-03-31")
    prices = pd.Series(np.linspace(100, 130, len(days)), index=days)
    monthly = to_monthly_returns(prices)
    jan_last = prices[prices.index.month == 1].iloc[-1]
    feb_last = prices[prices.index.month == 2].iloc[-1]
    assert monthly.iloc[0] == pytest.approx(feb_last / jan_last - 1)
    assert len(monthly) == 2  # February and March; January has no prior month
