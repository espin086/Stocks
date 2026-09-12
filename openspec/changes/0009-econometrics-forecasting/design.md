# 0009 — Design

## The econ extra, gated at the call

`statsmodels` and `arch` stay in the `econ` extra. `core/timeseries.py` and
`core/regression.py` import both lazily, so the base install imports the
modules and registers the commands; the first call without the extra raises
`ConfigurationError` (exit 3) with the exact install hint and no traceback.
`sobres doctor` lists both packages under the extra.

## Symbols: FRED or ticker, explicitly

`econ forecast CPIAUCSL`, `econ diagnose DGS10`, `econ volatility SPY` and
`econ regress --y AAPL --x SPY DGS10` mix macro series and tickers. A bare
symbol is read as a FRED series when it carries a digit or is longer than five
characters, otherwise as a ticker; `fred:` and `ticker:` prefixes override and
`--source` sets the default. Prices become simple returns for volatility and
regression and stay levels for forecasting and diagnosis; macro levels are
first-differenced for regression; the transform is printed.

## Stationarity first

`diagnose` reports ADF (H0 unit root) and KPSS (H0 stationary) with
statistics, p-values and lags, and when they disagree it says so in words
rather than picking one. `arima_forecast` with no order differences the series
until ADF rejects a unit root, at most twice, reports the `d` used, and refuses
beyond `d = 2`. Order selection is a small grid over `(p, q)` by AIC or BIC;
the chosen order and the next two candidates with their scores are in the
header. Residuals get a Ljung-Box test, and a failure is stated as evidence of
an inadequate model whose intervals are too narrow.

## Intervals everywhere

A forecast frame has five columns — the point, 80% and 95% bounds — in every
format. Volatility forecasts use `arch`'s simulated forecasts (seeded; the seed
is printed) and report the percentile bands of the simulated variance paths,
annualized with the conventions table; the one-step GARCH variance is known
and its band collapses, which is the truth, not a bug.

## GARCH into the optimizer

`covariance(returns, method="garch")` builds Bollerslev's constant-conditional-
correlation matrix: one-step GARCH(1,1) variances on the diagonal, the sample
correlation off it, then the same PSD conditioning every estimator gets.

## Rejected

| Choice | Rejected | Why |
|---|---|---|
| Grid search with the runners-up shown | `pmdarima` auto-ARIMA | Another dependency, and a black-box choice the spec forbids presenting as authoritative |
| CCC-GARCH covariance | DCC-GARCH | DCC adds parameters that are unstable on the windows this tool uses; CCC is the honest first step |
| Simulated volatility bands | Analytic variance-of-variance | `arch` provides simulation for every model; analytic bands exist only for some |
| Heuristic FRED/ticker split with prefixes | A separate `--fred` list flag | The proposal's examples pass bare symbols; the prefix keeps them explicit when it matters |
