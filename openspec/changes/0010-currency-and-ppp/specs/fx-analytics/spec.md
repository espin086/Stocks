# fx-analytics — spec delta (0010)

## ADDED Requirements

### Requirement: Currency return decomposition

The system SHALL separate what the asset did from what the currency did.

#### Scenario: Decomposition
- **WHEN** `decompose_return(local_returns, fx_returns)` is called
- **THEN** it SHALL return the local return, the currency return, the cross term,
  and the total in base currency
- **AND** the four SHALL reconcile exactly: `total = local + fx + local*fx`

#### Scenario: The cross term is reported, not hidden
- **WHEN** a decomposition is displayed
- **THEN** the cross term SHALL be shown as its own component
- **AND** SHALL NOT be folded into either side, which would misattribute
  compounding to the asset or the currency

#### Scenario: Multi-period attribution compounds
- **WHEN** a decomposition covers more than one period
- **THEN** each component SHALL be compounded geometrically over the window
- **AND** the compounded components SHALL reconcile to the compounded total

#### Scenario: Per-asset attribution
- **WHEN** `sobres fx attribution --tickers NESN.SW 7203.T --base USD` runs
- **THEN** one row per ticker SHALL print with its local return, currency return,
  cross term, total, and the currency it is denominated in
- **AND** a portfolio-level row SHALL aggregate them by weight

### Requirement: Currency contribution to risk

#### Scenario: Risk decomposition
- **WHEN** a portfolio holds assets in more than one currency
- **THEN** the system SHALL report total volatility in base currency, the
  volatility that would have obtained with currencies held fixed, and the
  difference attributable to currency exposure

#### Scenario: Correlation is not assumed away
- **WHEN** currency risk is reported
- **THEN** the correlation between each asset's local return and its currency
  return SHALL be reported
- **AND** the output SHALL NOT present currency risk as simply additive, since a
  negative correlation reduces total risk and a positive one amplifies it

#### Scenario: Net currency exposure
- **WHEN** a multi-currency portfolio is analyzed
- **THEN** exposure by currency SHALL be reported as a share of portfolio value

### Requirement: Hedged returns

#### Scenario: Construction
- **WHEN** a hedged return series is constructed
- **THEN** it SHALL be the local return plus the forward premium implied by the
  short-term interest-rate differential between the two currencies, under covered
  interest parity
- **AND** the rates used and their source SHALL be reported

#### Scenario: Assumptions are stated at the point of use
- **WHEN** any hedged figure is displayed
- **THEN** the output SHALL state that it is an interest-rate-differential
  approximation of a rolling hedge, excluding transaction costs, bid-ask spread,
  and basis
- **AND** SHALL NOT present it as an achievable realized return

#### Scenario: Comparison
- **WHEN** `sobres fx hedge --tickers ... --base USD --compare unhedged` runs
- **THEN** the risk panel from 0002 SHALL print for both hedged and unhedged
  series side by side
- **AND** the hedge's cumulative cost or benefit over the window SHALL be reported

#### Scenario: Missing rate data
- **WHEN** short-term rates are unavailable for a currency over the window
- **THEN** `InsufficientDataError` SHALL be raised naming the currency and series
- **AND** an unhedged result SHALL NOT be silently returned in its place

### Requirement: Optimization in a base currency

#### Scenario: Base currency is explicit
- **WHEN** any `sobres optimize` command receives assets in more than one currency
- **THEN** `--base` SHALL be required
- **AND** returns SHALL be converted per 0001 before any moment is estimated

#### Scenario: FX risk reaches the covariance matrix
- **WHEN** a covariance matrix is estimated from converted returns
- **THEN** currency co-movement SHALL be present in it by construction
- **AND** the output SHALL state which base currency the result is optimal in,
  since the optimum differs by base

#### Scenario: Hedged optimization
- **WHEN** `--hedged` is supplied
- **THEN** the optimization SHALL run on hedged return series
- **AND** the result SHALL be labelled as such, carrying the hedging assumptions

### Requirement: FX commands

#### Scenario: Rates
- **WHEN** `sobres fx rates EURUSD USDJPY --start 2015-01-01` runs
- **THEN** a date-indexed table of those pairs SHALL print, with the provider and
  any carried-forward dates noted

#### Scenario: Conversion
- **WHEN** `sobres fx convert 100000 --from USD --to EUR --on 2026-09-01` runs
- **THEN** the converted amount, the rate used, its date, and its source SHALL print
- **AND** if the rate was carried forward from an earlier date, that SHALL be stated

#### Scenario: No forecasting surface
- **WHEN** the `sobres fx` group is listed
- **THEN** no subcommand SHALL project, forecast, or recommend a future rate
