# purchasing-power — spec delta (0010)

## ADDED Requirements

### Requirement: Absolute and relative PPP are distinct

Conflating them is the most common error in applied PPP work, so the API keeps
them separate and each output names which it used.

#### Scenario: Absolute PPP
- **WHEN** absolute PPP is requested
- **THEN** it SHALL be the published conversion factor — units of local currency
  per unit of the base currency buying an equivalent basket — sourced from a
  statistical office, not computed from price indices
- **AND** the benchmark year and data vintage SHALL be reported with it

#### Scenario: Relative PPP
- **WHEN** relative PPP is requested
- **THEN** it SHALL be the change in the nominal rate implied by the inflation
  differential from a stated base date
- **AND** the base date SHALL be explicit, since relative PPP says nothing about
  the level, only the change from an anchor

#### Scenario: Each result names its method
- **WHEN** any PPP figure is displayed
- **THEN** it SHALL state whether it is absolute or relative, and for relative,
  its base date

#### Scenario: They are never combined silently
- **WHEN** a computation would mix an absolute conversion factor with a relative
  drift
- **THEN** `UsageError` SHALL be raised

### Requirement: Real exchange rates and valuation gaps

#### Scenario: Real exchange rate
- **WHEN** a real exchange rate is computed
- **THEN** it SHALL be the nominal rate adjusted by the ratio of the two price
  levels, with the index and base period named

#### Scenario: Over- and undervaluation
- **WHEN** `sobres ppp compare --base USD --vs EUR GBP MXN` runs
- **THEN** each row SHALL show the market rate, the PPP rate, and the percentage
  gap between them
- **AND** the gap SHALL be labelled as a valuation gap, not as an expected move

#### Scenario: Direction is unambiguous
- **WHEN** a gap is reported
- **THEN** the output SHALL state which currency is over- or undervalued and
  against which, in words as well as sign

#### Scenario: Real effective exchange rates are taken, not invented
- **WHEN** a trade-weighted real effective exchange rate is reported
- **THEN** it SHALL be a published BIS series
- **AND** the system SHALL NOT construct its own trade weights, which would be an
  unvalidated model presented as data

### Requirement: PPP is never presented as a forecast

#### Scenario: Mandatory framing
- **WHEN** any PPP result is displayed
- **THEN** it SHALL state that PPP is a long-run relationship with little
  short-run predictive power for exchange rates

#### Scenario: No implied trade
- **WHEN** a valuation gap is reported
- **THEN** the output SHALL NOT describe it as cheap, expensive, an opportunity,
  or a signal, and SHALL NOT project a convergence path or date

#### Scenario: Persistent gaps are expected, not anomalies
- **WHEN** a gap has persisted across the reported window
- **THEN** the output SHALL note that sustained deviations are normal, driven by
  productivity differences, non-traded goods, and trade barriers

### Requirement: PPP-adjusted goal planning

#### Scenario: Restating a goal
- **WHEN** `sobres ppp adjust-goal --goal fire --to PRT` runs
- **THEN** the goal's target from 0008 SHALL be restated at the destination's
  price level, showing the original, the PPP factor, and the adjusted target
- **AND** the equivalent figure at the market exchange rate SHALL be shown
  alongside, since the two differ and the difference is the point

#### Scenario: The basket limitation is stated
- **WHEN** a goal is PPP-adjusted
- **THEN** the output SHALL state that PPP reflects a national consumption
  basket, which may not match the user's spending
- **AND** the adjustment SHALL be presented as a scale factor with its basis
  named, not as a personalized budget

#### Scenario: Effect on the plan
- **WHEN** a goal is restated
- **THEN** the effect on years-to-goal and the projected date SHALL be recomputed
  and shown against the original

#### Scenario: Nothing beyond price levels is modeled
- **WHEN** a destination is analyzed
- **THEN** the output SHALL state that tax, residency, healthcare, and currency
  risk on the income stream are not modeled
- **AND** no command SHALL rank or recommend destinations

#### Scenario: Income and target currency may differ
- **WHEN** a goal is funded in one currency and spent in another
- **THEN** the output SHALL note that the plan carries exchange-rate risk between
  them, and SHALL NOT assume a constant future rate

### Requirement: PPP data sourcing

#### Scenario: Provider protocol
- **WHEN** PPP or price-level data is fetched
- **THEN** it SHALL be through a `PppProvider` protocol, cached through the
  storage port like every other dataset

#### Scenario: Keyless default
- **WHEN** no provider is configured
- **THEN** World Bank ICP series SHALL be used, requiring no API key
- **AND** OECD PPP and comparative price levels SHALL be available as an
  alternative

#### Scenario: Vintage is carried
- **WHEN** any PPP figure is returned
- **THEN** its benchmark year, reference period, and release date SHALL travel
  with it and appear in output

#### Scenario: Stale data is flagged
- **WHEN** the most recent available PPP observation is older than a configurable
  threshold, defaulting to three years
- **THEN** the output SHALL flag it as stale with its age

#### Scenario: Missing coverage
- **WHEN** a requested country has no PPP series
- **THEN** `InsufficientDataError` SHALL be raised naming the country code and
  the series, and listing which requested countries were available

#### Scenario: Country codes are unambiguous
- **WHEN** a country is specified
- **THEN** ISO 3166-1 alpha-3 codes SHALL be accepted
- **AND** an unrecognized code SHALL raise `UsageError` rather than resolve to a
  near match
