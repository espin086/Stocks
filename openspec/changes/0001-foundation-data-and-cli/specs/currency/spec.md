# currency — spec delta (0001)

Currency is handled like timezone: a property every series carries, converted by
one explicit operation, never mixed silently. The analytics live in 0010; the
model that makes them possible has to exist before anything computes a return.

## ADDED Requirements

### Requirement: Every monetary series declares its currency

#### Scenario: Price frames carry currency
- **WHEN** a provider returns a price frame
- **THEN** `frame.attrs["currency"]` SHALL hold the ISO 4217 code the prices are
  denominated in
- **AND** a frame whose columns are not all in one currency SHALL instead carry a
  per-column currency mapping

#### Scenario: Currency is discovered, not assumed
- **WHEN** a ticker's prices are fetched
- **THEN** the currency SHALL come from the provider's own metadata
- **AND** SHALL NOT be inferred from the exchange suffix or defaulted to USD —
  a London listing may be quoted in pence, not pounds

#### Scenario: Sub-unit quotations
- **WHEN** a provider quotes in a currency sub-unit (GBp, ZAc, ILA)
- **THEN** the data layer SHALL normalize to the major unit and record the major
  unit's code
- **AND** a test SHALL cover at least one such listing, because a silent
  hundred-fold error is the failure mode here

#### Scenario: Unknown currency
- **WHEN** a provider returns no currency metadata for an instrument
- **THEN** `ProviderError` SHALL be raised naming the symbol
- **AND** the system SHALL NOT guess

### Requirement: Unambiguous rate representation

The direction of a quoted rate is the most common source of silent error in FX
code. It is settled by type, not by convention memorized per call site.

#### Scenario: Pairs are typed
- **WHEN** an exchange rate is represented
- **THEN** it SHALL carry a `CurrencyPair(base, quote)` and mean **units of
  `quote` per one unit of `base`**
- **AND** `CurrencyPair("EUR", "USD")` at 1.08 SHALL mean one euro buys 1.08
  dollars

#### Scenario: Call sites never multiply or divide by a rate
- **WHEN** any code converts an amount or a series between currencies
- **THEN** it SHALL call the conversion function with the two currency codes
- **AND** SHALL NOT apply a raw rate itself, so inversion cannot be got wrong

#### Scenario: Inversion is exact where it must be
- **WHEN** a rate is inverted to serve the opposite direction
- **THEN** converting an amount out and back SHALL return the original within
  floating-point tolerance

#### Scenario: Cross rates are triangulated consistently
- **WHEN** a pair is requested that the provider does not quote directly
- **THEN** it SHALL be derived through the provider's base currency
- **AND** the derived rate SHALL be consistent with the two rates it came from,
  asserted by a test

### Requirement: Exchange-rate data

#### Scenario: Provider protocol
- **WHEN** exchange rates are fetched
- **THEN** it SHALL be through an `FxProvider` protocol, alongside the price,
  macro, and factor protocols
- **AND** its returned frame SHALL follow the canonical shape, indexed by
  tz-naive date with one column per requested pair

#### Scenario: Keyless default
- **WHEN** no provider is configured
- **THEN** ECB euro reference rates SHALL be used, requiring no API key
- **AND** FRED's `DEX*` series SHALL be available as an alternative for
  USD-based pairs

#### Scenario: Non-trading days
- **WHEN** a rate is requested for a date the FX market did not quote
- **THEN** the most recent prior quote SHALL be used
- **AND** the frame SHALL record that a carry-forward occurred, so downstream
  reporting can say so

#### Scenario: Calendar mismatch is explicit
- **WHEN** a price series and a rate series are combined
- **THEN** they SHALL be aligned through `align_frames`, as any two sources are
- **AND** a date present in prices but absent from rates SHALL be resolved by
  the carry-forward rule above, never dropped silently

#### Scenario: Rates are cached like any other observation
- **WHEN** rates are fetched
- **THEN** they SHALL be stored through the storage port with the same TTL,
  sub-range reuse, and provenance rules as prices

### Requirement: Conversion is explicit and correct

#### Scenario: Converting a price series
- **WHEN** a price series is converted to another currency
- **THEN** each observation SHALL be multiplied by that date's rate
- **AND** the result's `attrs["currency"]` SHALL be updated

#### Scenario: Converting a return series
- **WHEN** a return series in a local currency is expressed in a base currency
- **THEN** the result SHALL be `(1 + r_local) * (1 + r_fx) - 1`
- **AND** it SHALL NOT be approximated as `r_local + r_fx`, which drops the
  cross term and misstates compounded results
- **AND** a test SHALL assert the identity against converting the price series
  first and differencing it

#### Scenario: Mixed currencies are refused, not guessed
- **WHEN** an operation receives series in more than one currency and no target
  currency
- **THEN** `UsageError` SHALL be raised naming the currencies found
- **AND** no computation SHALL proceed on mixed units

#### Scenario: Single-currency work is unaffected
- **WHEN** every input is already in one currency
- **THEN** no rate SHALL be fetched and no conversion performed
- **AND** results SHALL be identical to a build with no currency support

### Requirement: Currency appears in output

#### Scenario: Results state their currency
- **WHEN** any monetary or return result is rendered
- **THEN** the currency SHALL be stated
- **AND** where conversion occurred, the output SHALL name the source currency
  and the rate source

#### Scenario: Conversion is an assumption worth logging
- **WHEN** a conversion is performed as part of a computation
- **THEN** it SHALL be logged at INFO, and a carry-forward of a stale rate at
  WARNING, under 0001's rule that assumptions affecting a number are visible
