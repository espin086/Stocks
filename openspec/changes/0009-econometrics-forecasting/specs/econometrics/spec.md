# econometrics — spec delta (0009)

## ADDED Requirements

### Requirement: Stationarity diagnostics

#### Scenario: Tests reported
- **WHEN** `qf econ diagnose <series>` runs
- **THEN** ADF and KPSS test statistics, p-values, and conclusions SHALL be reported
- **AND** disagreement between the two SHALL be stated explicitly rather than
  resolved silently

#### Scenario: ACF and PACF
- **WHEN** diagnostics run
- **THEN** ACF and PACF values through lag 20 SHALL be reported with their
  significance bounds

### Requirement: ARIMA forecasting

#### Scenario: Stationarity is enforced before fitting
- **WHEN** a non-stationary series is passed to an ARIMA fit with `d` unspecified
- **THEN** the series SHALL be differenced to stationarity and the order `d` used
  SHALL be reported
- **AND** if stationarity cannot be reached by `d=2`, the fit SHALL fail with a
  message saying so

#### Scenario: Order selection is transparent
- **WHEN** `--auto` selects an order
- **THEN** the chosen `(p,d,q)`, the information criterion used, and the next two
  best candidates with their scores SHALL be reported

#### Scenario: Intervals are mandatory
- **WHEN** any forecast is produced
- **THEN** the output SHALL include 80% and 95% prediction intervals
- **AND** a point forecast SHALL NOT be emitted without them in any output format

#### Scenario: Residual diagnostics
- **WHEN** a model is fitted
- **THEN** the Ljung-Box statistic on residuals SHALL be reported, and a failure
  SHALL be flagged as evidence the model is inadequate

### Requirement: Volatility forecasting

#### Scenario: GARCH fit
- **WHEN** `qf econ volatility SPY --model garch` runs
- **THEN** a GARCH(1,1) model SHALL be fitted to returns and a conditional
  volatility forecast SHALL be produced with intervals
- **AND** `--model` SHALL also accept `egarch` and `ewma`

#### Scenario: Annualized output
- **WHEN** volatility is reported
- **THEN** it SHALL be annualized using the 0002 conventions table and labeled as
  annualized

#### Scenario: Feeds the optimizer
- **WHEN** `covariance(returns, method="garch")` is called from 0002's estimator
  registry
- **THEN** a GARCH-implied covariance matrix SHALL be returned, subject to the same
  PSD guarantees as every other estimator

### Requirement: Regression with robust inference

#### Scenario: Robust standard errors
- **WHEN** `qf econ regress --robust <kind>` runs
- **THEN** `hac`, `hc0`–`hc3`, and `none` SHALL be accepted, and the kind used SHALL
  be named in the output

#### Scenario: Multicollinearity
- **WHEN** two or more regressors are supplied
- **THEN** the VIF per regressor SHALL be reported, and any VIF above 10 flagged

#### Scenario: Diagnostics reported
- **WHEN** a regression completes
- **THEN** R², adjusted R², F-statistic with p-value, Durbin-Watson, and a
  heteroskedasticity test SHALL be reported

### Requirement: Dependency gating

#### Scenario: Missing extra
- **WHEN** a `qf econ` command runs without the `econ` extra installed
- **THEN** the system SHALL exit 3 with
  `This command needs the econ extra. Install it with: pip install 'quantfolio[econ]'`
- **AND** SHALL NOT emit an `ImportError` traceback
