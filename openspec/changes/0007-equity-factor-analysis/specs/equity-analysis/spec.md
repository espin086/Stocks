# equity-analysis — spec delta (0007)

## ADDED Requirements

### Requirement: Factor model regression

The system SHALL regress an asset's excess returns on published factor returns.

#### Scenario: Supported models
- **WHEN** `factor_regression(returns, model=m)` is called
- **THEN** `m` SHALL accept `"capm"`, `"ff3"`, `"ff5"`, and `"ff5+mom"`

#### Scenario: Excess returns, not raw
- **WHEN** any factor regression runs
- **THEN** the dependent variable SHALL be `r_asset - RF` using the `RF` column from
  the same factor file, not a separately sourced risk-free rate

#### Scenario: Reported statistics
- **WHEN** a regression completes
- **THEN** the result SHALL include, per factor: coefficient, standard error,
  t-statistic, and p-value
- **AND** for the intercept (alpha): the same four, plus the annualized alpha
- **AND** model-level: R², adjusted R², observation count, and the sample window

#### Scenario: Robust standard errors
- **WHEN** a regression completes
- **THEN** Newey-West (HAC) standard errors SHALL be reported alongside OLS
  standard errors
- **AND** the lag length used SHALL be stated

#### Scenario: Alpha is reported honestly
- **WHEN** alpha's p-value exceeds `0.05`
- **THEN** the output SHALL state that alpha is not statistically distinguishable
  from zero at the 5% level
- **AND** SHALL NOT present the point estimate without that qualification

#### Scenario: Minimum sample
- **WHEN** fewer than 36 monthly observations (or 252 daily) are available
- **THEN** `InsufficientDataError` SHALL be raised naming the count available and
  the count required

#### Scenario: Default frequency
- **WHEN** `--frequency` is not specified for a factor command
- **THEN** monthly SHALL be used, matching the publication frequency of the factors

#### Scenario: Rolling betas
- **WHEN** `--rolling 36` is supplied
- **THEN** a frame of factor loadings per rolling 36-period window SHALL be returned,
  so exposure instability is visible

### Requirement: Single-stock analysis

#### Scenario: Stock dashboard
- **WHEN** `sobres analyze stock NVDA` runs
- **THEN** the output SHALL include price summary, annualized return and volatility,
  the full risk panel from 0002, CAPM beta against `Mkt-RF`, and a fundamentals
  block (market cap, P/E, P/B, dividend yield, sector)

#### Scenario: Fundamentals limitation is stated
- **WHEN** any fundamentals value is displayed
- **THEN** the output SHALL note that fundamentals are current values, not
  point-in-time, and are therefore unsuitable for backtesting

#### Scenario: Missing fundamentals
- **WHEN** the provider returns no fundamentals for a symbol (common for ETFs)
- **THEN** the fundamentals block SHALL be omitted with a one-line note, and the
  price and risk sections SHALL still render

### Requirement: Multi-ticker factor comparison

#### Scenario: Comparison table
- **WHEN** `sobres analyze factors --tickers AAPL MSFT NVDA --model ff5` runs
- **THEN** one row per ticker SHALL print with its factor loadings, alpha,
  alpha t-statistic, and R²
- **AND** rows SHALL be ordered as supplied, so output is diffable across runs
