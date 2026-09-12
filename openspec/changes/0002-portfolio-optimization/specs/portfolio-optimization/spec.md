# portfolio-optimization — spec delta (0002)

## ADDED Requirements

### Requirement: Return computation and conventions

The system SHALL convert price series to returns under one documented convention.

#### Scenario: Simple returns
- **WHEN** `simple_returns(prices)` is called
- **THEN** the result SHALL be `P_t / P_{t-1} - 1`, with the first row dropped

#### Scenario: Log returns
- **WHEN** `log_returns(prices)` is called
- **THEN** the result SHALL be `ln(P_t / P_{t-1})`

#### Scenario: Annualization
- **WHEN** a daily return series is annualized
- **THEN** mean SHALL scale by `252` and volatility by `sqrt(252)`
- **AND** the periods-per-year constant SHALL come from `PERIODS_PER_YEAR[frequency]`
  (`daily=252, weekly=52, monthly=12, quarterly=4, annual=1`), never a literal

#### Scenario: Geometric vs arithmetic
- **WHEN** `annualized_return(returns, method="geometric")` is called
- **THEN** the result SHALL be `(∏(1+r))^(periods_per_year/n) - 1`
- **AND** `method="arithmetic"` SHALL return `mean(r) * periods_per_year`
- **AND** the default SHALL be `"geometric"`, because it is what an investor
  actually earns

#### Scenario: Missing observations
- **WHEN** a return series contains `NaN`
- **THEN** the caller SHALL choose `drop` or `zero` explicitly via a parameter with
  no default, so the choice is never silent

### Requirement: One currency per computation

#### Scenario: Single currency needs no ceremony
- **WHEN** every asset in a computation shares a currency
- **THEN** it SHALL proceed with no rate fetch and no conversion
- **AND** results SHALL be identical to a build without currency support

#### Scenario: Mixed currencies require a base
- **WHEN** assets span more than one currency and no `--base` is given
- **THEN** `UsageError` SHALL be raised naming the currencies found
- **AND** no moment SHALL be estimated on mixed units

#### Scenario: Conversion precedes estimation
- **WHEN** `--base` is supplied for a multi-currency set
- **THEN** returns SHALL be converted per 0001's exact identity **before**
  expected returns or covariance are estimated
- **AND** converting the resulting statistics instead SHALL NOT be done, since
  covariance does not transform that way

#### Scenario: Results name their base
- **WHEN** any result derived from converted returns is rendered
- **THEN** the base currency SHALL be stated
- **AND** the output SHALL note that the optimum is specific to that base

### Requirement: Expected-return and covariance estimators

The system SHALL treat the optimizer's inputs as pluggable estimators.

#### Scenario: Available estimators
- **WHEN** `expected_returns(returns, method=m)` is called
- **THEN** `m` SHALL accept `"mean_historical"`, `"ewma"`, and `"capm"`

#### Scenario: Covariance estimators
- **WHEN** `covariance(returns, method=m)` is called
- **THEN** `m` SHALL accept `"sample"`, `"ledoit_wolf"`, `"ewma"`, and
  `"semicovariance"`

#### Scenario: Shrinkage is the default
- **WHEN** `method` is not specified for `covariance`
- **THEN** `"ledoit_wolf"` SHALL be used
- **AND** the returned matrix's `attrs["shrinkage"]` SHALL record the intensity

#### Scenario: Insufficient observations
- **WHEN** the number of observations is less than or equal to the number of assets
- **THEN** `InsufficientDataError` SHALL be raised, naming both counts and stating
  that the sample covariance matrix is singular

#### Scenario: Every covariance matrix is usable
- **WHEN** any estimator returns a matrix
- **THEN** it SHALL be symmetric to within `1e-10`
- **AND** SHALL be positive semi-definite, or repaired by nearest-PSD projection
  with a warning to stderr naming the smallest original eigenvalue

### Requirement: Risk metrics

The system SHALL compute a standard risk panel from a return series.

#### Scenario: Metrics available
- **WHEN** `risk_metrics(returns, risk_free)` is called
- **THEN** the result SHALL include annualized volatility, Sharpe, Sortino, max
  drawdown, Calmar, historical VaR(95), CVaR(95), skew, and kurtosis

#### Scenario: Sharpe ratio definition
- **WHEN** Sharpe is computed
- **THEN** it SHALL be `(annualized_return - annualized_risk_free) / annualized_vol`
- **AND** the risk-free input SHALL be a decimal annual rate, defaulting to the FRED
  3-month Treasury over the same window, or `0.0` if FRED is unavailable — with a
  stderr note saying which was used

#### Scenario: Sortino uses downside deviation
- **WHEN** Sortino is computed
- **THEN** the denominator SHALL be the annualized standard deviation of returns
  below the target (default `0.0`), not total volatility

#### Scenario: Max drawdown
- **WHEN** max drawdown is computed
- **THEN** the result SHALL be the most negative `(V_t / max(V_{0..t})) - 1` over the
  cumulative wealth series
- **AND** the peak date, trough date, and recovery date (or `None`) SHALL be returned

#### Scenario: Beta against a benchmark
- **WHEN** `beta(asset_returns, benchmark_returns)` is called
- **THEN** the result SHALL be `cov(a, b) / var(b)` over the aligned overlap
- **AND** `AlignmentError` SHALL be raised if fewer than 30 overlapping observations

### Requirement: Mean-variance optimization

The system SHALL solve constrained mean-variance problems.

#### Scenario: Supported objectives
- **WHEN** `optimize(mu, sigma, objective=o, constraints=c)` is called
- **THEN** `o` SHALL accept `"min_variance"`, `"max_sharpe"`, `"target_return"`,
  `"target_risk"`, `"risk_parity"`, and `"equal_weight"`

#### Scenario: Weights are a valid portfolio
- **WHEN** any optimization succeeds
- **THEN** the weights SHALL sum to `1.0` within `1e-8`
- **AND** SHALL satisfy every supplied bound within `1e-8`

#### Scenario: Long-only by default
- **WHEN** no bounds are supplied
- **THEN** weights SHALL be constrained to `[0, 1]`
- **AND** `--allow-short` SHALL relax the lower bound to `-1`

#### Scenario: Position limits
- **WHEN** `--max-weight 0.35` is supplied
- **THEN** no asset's weight SHALL exceed `0.35`
- **AND** if `max_weight * n_assets < 1.0`, `UsageError` SHALL be raised stating
  the constraint is infeasible

#### Scenario: Target return infeasible
- **WHEN** `objective="target_return"` with a target above the maximum attainable
- **THEN** `InsufficientDataError` SHALL be raised naming the attainable maximum

#### Scenario: Max-Sharpe correctness
- **WHEN** `objective="max_sharpe"` is solved for a two-asset case with known
  closed-form tangency weights
- **THEN** the solution SHALL match the analytic answer within `1e-6`

#### Scenario: Solver failure is never silent
- **WHEN** the underlying solver does not converge
- **THEN** `OptimizationError` SHALL be raised with the solver's status message
- **AND** no weight vector SHALL be returned

#### Scenario: Concentration warning
- **WHEN** any single weight exceeds `0.50` and no explicit `--max-weight` was given
- **THEN** a stderr warning SHALL note that unconstrained mean-variance solutions
  concentrate, and suggest `--max-weight`

#### Scenario: Determinism
- **WHEN** the same inputs are optimized twice
- **THEN** the weights SHALL be identical bit-for-bit

### Requirement: Efficient frontier

#### Scenario: Frontier generation
- **WHEN** `efficient_frontier(mu, sigma, n_points=50)` is called
- **THEN** 50 portfolios SHALL be returned spanning min-variance return to max
  attainable return
- **AND** each SHALL carry its weights, expected return, volatility, and Sharpe

#### Scenario: Monotonicity
- **WHEN** frontier points are sorted by expected return ascending
- **THEN** volatility SHALL be non-decreasing across the efficient portion
  (this is the invariant that catches a broken solver)

#### Scenario: Named points identified
- **WHEN** a frontier is returned
- **THEN** the minimum-variance and maximum-Sharpe portfolios SHALL be flagged

### Requirement: Walk-forward backtest

The system SHALL evaluate an optimization strategy out-of-sample.

#### Scenario: No lookahead
- **WHEN** weights are computed for a rebalance date `t`
- **THEN** only returns strictly before `t` SHALL be used
- **AND** a test SHALL assert that perturbing data at or after `t` leaves those
  weights unchanged

#### Scenario: Rebalancing frequencies
- **WHEN** `--rebalance` is supplied
- **THEN** `monthly`, `quarterly`, `annual`, and `never` SHALL be accepted

#### Scenario: Transaction costs
- **WHEN** `--cost-bps 10` is supplied
- **THEN** each rebalance SHALL deduct `0.0010 * turnover` from the portfolio value
- **AND** turnover SHALL be `0.5 * Σ|w_new - w_drifted|`
- **AND** the default SHALL be `10` bps, not `0` — a costless backtest flatters
  every high-turnover strategy

#### Scenario: Weight drift between rebalances
- **WHEN** no rebalance occurs on a given day
- **THEN** weights SHALL drift with realized returns, not be held constant

#### Scenario: Benchmark comparison
- **WHEN** a backtest completes
- **THEN** the result SHALL include the strategy's risk panel, an equal-weight
  benchmark's panel over the same window, and total turnover and costs paid

#### Scenario: Insufficient lookback
- **WHEN** the first rebalance date has less than the requested lookback available
- **THEN** the backtest SHALL start at the first date that does have it, and report
  the actual start on stderr

### Requirement: `qf optimize` command group

#### Scenario: Markowitz
- **WHEN** `qf optimize markowitz --tickers AAPL MSFT --start 2015-01-01` runs
- **THEN** a weights table SHALL print with the portfolio's expected return,
  volatility, and Sharpe
- **AND** the estimators used SHALL be named in the output header

#### Scenario: Frontier
- **WHEN** `qf optimize frontier --tickers ... --points 50 --format csv` runs
- **THEN** CSV with one row per frontier point SHALL print, columns
  `ret, vol, sharpe, <one per ticker>`

#### Scenario: Backtest
- **WHEN** `qf optimize backtest ... --rebalance quarterly` runs
- **THEN** the strategy and benchmark panels SHALL print side by side
- **AND** the output SHALL state the out-of-sample window and total costs paid

#### Scenario: Risk panel of a given portfolio
- **WHEN** `qf optimize risk --tickers AAPL MSFT --weights 0.6 0.4` runs
- **THEN** the full risk panel for that fixed portfolio SHALL print

#### Scenario: Weights supplied must be valid
- **WHEN** `--weights` is supplied with a count differing from `--tickers`, or not
  summing to 1.0 within `1e-6`
- **THEN** `UsageError` SHALL be raised naming the discrepancy
