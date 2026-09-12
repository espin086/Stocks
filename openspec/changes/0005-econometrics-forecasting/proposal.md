---
change: 0005-econometrics-forecasting
milestone: v1.3
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization, 0003-equity-factor-analysis]
status: proposed
planning_depth: proposal + spec delta (design and tasks written when 0004 lands)
---

# 0005 — Econometrics and forecasting

## Outcome

```bash
qf econ forecast CPIAUCSL --model arima --horizon 12
qf econ volatility SPY --model garch --horizon 30
qf econ diagnose DGS10          # stationarity, ACF/PACF, structural breaks
qf econ regress --y AAPL --x SPY DGS10 --robust hac
```

Time-series forecasting and regression diagnostics on the same data layer, with
honest uncertainty intervals.

## Why

Volatility forecasting feeds directly back into 0002: a GARCH-based covariance
estimator is a meaningfully better input to the optimizer than a rolling sample
window, particularly during regime shifts. Macro forecasting supports the real-return
assumptions in 0004.

It is last because it is the piece whose value depends most on everything below it
being trustworthy first.

## What changes

- **New capability `econometrics`**: `core/timeseries.py` (stationarity tests,
  differencing, ARIMA, GARCH, forecast intervals) and `core/regression.py` (OLS with
  robust standard errors, multicollinearity and residual diagnostics).
- **New CLI group `qf econ`**: `forecast`, `volatility`, `diagnose`, `regress`.
- A GARCH-based covariance estimator registered into 0002's `core/moments.py`, which
  is why that module was built as a pluggable registry.
- Reuse: `espin086/Econometrics` for statsmodels patterns, `espin086/jjutils`
  `base_regression.py` for regression scaffolding, `espin086/NewsWaveMetrics` for
  its existing forecasting work.

## Non-goals

- No VAR, VECM, or cointegration analysis in v1.3.
- No machine-learning forecasters. A tool that ships an LSTM price predictor next to
  a Fama-French regression is telling the user something false about both.
- No causal inference (diff-in-diff, IV, RDD). `espin086/Econometrics` holds that
  work and it does not belong in an equity CLI.
- No automatic model selection presented as authoritative — see risks.

## Risks

| Risk | Mitigation |
|---|---|
| Point forecasts read as predictions | Prediction intervals are mandatory in every forecast output, never optional; the point forecast is never shown alone |
| Auto-ARIMA overfits and reads as objective | Report the selected order **and** the information criterion, plus the top 3 candidate models, so the choice is visible rather than authoritative |
| Non-stationary input silently produces nonsense | Stationarity is tested before fitting; non-stationary series either fail loudly or are differenced with the differencing order reported |
| `statsmodels` and `arch` dependency weight | Both stay in the opt-in `econ` extra; commands that need them exit 3 with an install hint |
