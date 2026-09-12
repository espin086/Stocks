# market-data — spec delta (0001)

## ADDED Requirements

### Requirement: Provider protocols

The system SHALL define three typed protocols in `quantfolio.data.base` that every
data source implements, so that call sites depend on the protocol and never on a
concrete vendor.

- `PriceProvider.get_prices(tickers, start, end, field) -> pd.DataFrame`
- `MacroProvider.get_series(series_ids, start, end) -> pd.DataFrame`
- `FactorProvider.get_factors(model, frequency, start, end) -> pd.DataFrame`

#### Scenario: A concrete provider satisfies the protocol
- **WHEN** `YFinanceProvider` is checked against `PriceProvider` at type-check time
- **THEN** `mypy --strict` SHALL report no error
- **AND** a shared contract test suite SHALL run against every registered provider

#### Scenario: Call sites are vendor-agnostic
- **WHEN** any code outside `quantfolio.data` needs prices
- **THEN** it SHALL accept a `PriceProvider` and SHALL NOT import a vendor module

### Requirement: Canonical price frame shape

All price data SHALL be returned in one documented shape, regardless of source.

#### Scenario: Multi-ticker request
- **WHEN** `get_prices(["AAPL","MSFT"], start, end, field="adj_close")` succeeds
- **THEN** the result SHALL be a `DataFrame` indexed by tz-naive `DatetimeIndex`
  named `date`, ascending, with one column per ticker named by the ticker symbol
- **AND** the dtype of every column SHALL be `float64`

#### Scenario: A requested ticker does not exist
- **WHEN** a ticker returns no data from the provider
- **THEN** the system SHALL raise `UnknownTickerError` naming the symbol
- **AND** SHALL NOT silently return a frame with a missing column

#### Scenario: Partial history
- **WHEN** one ticker's history starts after the requested `start`
- **THEN** its early rows SHALL be `NaN` rather than dropped
- **AND** the caller SHALL decide alignment explicitly via `align_frames`

### Requirement: Explicit series alignment

The system SHALL provide `quantfolio.data.align_frames(*frames, how)` as the single
sanctioned way to combine series from different sources.

#### Scenario: Prices aligned to factor returns
- **WHEN** a daily price frame and a Ken French daily factor frame are aligned with
  `how="inner"`
- **THEN** the result SHALL contain only dates present in both
- **AND** the operation SHALL raise `AlignmentError` if the overlap is empty

#### Scenario: Timezone safety
- **WHEN** any provider returns a tz-aware index
- **THEN** the data layer SHALL normalize it to tz-naive dates before returning

### Requirement: yfinance price provider

The system SHALL provide `YFinanceProvider` requiring no API key.

#### Scenario: Adjusted close is the default
- **WHEN** `field` is not specified
- **THEN** the provider SHALL return split- and dividend-adjusted close prices
- **AND** the returned frame's `attrs["field"]` SHALL record which field was used

#### Scenario: Provider outage
- **WHEN** the upstream call raises or returns an empty payload
- **THEN** the system SHALL raise `ProviderError` carrying the provider name and
  the upstream message, and SHALL NOT emit a raw third-party traceback to stderr

### Requirement: FRED macro provider

The system SHALL provide `FredProvider` for Federal Reserve economic series.

#### Scenario: Key present
- **WHEN** `FRED_API_KEY` is set and `get_series(["DGS10"])` is called
- **THEN** the provider SHALL return a frame with a `DGS10` column of `float64`

#### Scenario: Key absent
- **WHEN** `FRED_API_KEY` is unset and a FRED-backed command is invoked
- **THEN** the system SHALL exit with code 3 and the message
  `FRED_API_KEY is not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html then run: qf config set fred_api_key <KEY>`
- **AND** SHALL NOT emit a traceback

#### Scenario: Risk-free rate helper
- **WHEN** `get_risk_free_rate(start, end, tenor="3m")` is called
- **THEN** the system SHALL return a decimal daily-frequency series (0.0525 for
  5.25%), converted from FRED's percentage convention

### Requirement: Ken French factor provider

The system SHALL provide `KenFrenchProvider` for Fama-French factor returns, with
no API key.

#### Scenario: Supported models
- **WHEN** `get_factors(model=m)` is called for `m` in `{"ff3", "ff5", "ff5+mom"}`
- **THEN** the frame SHALL contain exactly the columns for that model plus `RF`
  (`ff3` → `Mkt-RF, SMB, HML, RF`; `ff5` → `Mkt-RF, SMB, HML, RMW, CMA, RF`;
  `ff5+mom` → the `ff5` set plus `MOM`)

#### Scenario: Decimal convention
- **WHEN** any factor frame is returned
- **THEN** values SHALL be decimal returns, not percent
  (Ken French publishes percent; the provider SHALL divide by 100)
- **AND** a regression test SHALL assert `Mkt-RF` for a known month matches the
  published value / 100

#### Scenario: Unexpected file layout
- **WHEN** the downloaded archive does not match the expected multi-table layout
- **THEN** the provider SHALL raise `ProviderError` describing what it expected
- **AND** SHALL NOT return a partially-parsed frame

### Requirement: SQLite-backed cache

The system SHALL cache every provider response in a single SQLite database, so
that one file is the tool's entire local state — the property that makes the
Docker deployment in 0005 a single mounted volume.

#### Scenario: One database file
- **WHEN** the system stores anything locally
- **THEN** it SHALL be a single SQLite file, not a directory of loose artifacts
- **AND** the same file SHALL later hold the application state added in 0003

#### Scenario: Database location
- **WHEN** no override is configured
- **THEN** the default backend SHALL be SQLite in the platform user-data dir via
  `platformdirs`
- **AND** the backend and location SHALL be overridable by `QUANTFOLIO_DB_URL`,
  which 0005 sets to `sqlite:////data/quantfolio.db`

#### Scenario: Cache hit
- **WHEN** an identical request is made within the dataset's TTL
- **THEN** the response SHALL be served from the database without a network call
- **AND** the call SHALL complete in under 1 second for a 10-ticker, 10-year frame

#### Scenario: Partial-range reuse
- **WHEN** a request overlaps a cached range but extends beyond it
- **THEN** only the missing dates SHALL be fetched and merged with what is stored
- **AND** re-requesting a narrower range than one already cached SHALL make no
  network call at all

#### Scenario: Forced refresh
- **WHEN** any command is invoked with `--refresh`
- **THEN** the cache SHALL be bypassed and the fresh response written back

#### Scenario: Observation identity
- **WHEN** the same observation is fetched twice
- **THEN** it SHALL be stored once, keyed by `(provider, dataset, symbol, date)`
- **AND** the later fetch SHALL overwrite the earlier value, so provider
  revisions land rather than duplicate

#### Scenario: Concurrent access
- **WHEN** a CLI command and a running server touch the database at once
- **THEN** the connection SHALL use WAL mode with a busy timeout so a read never
  blocks a write into an error
- **AND** foreign-key enforcement SHALL be on for every connection

#### Scenario: Corrupt database
- **WHEN** the database fails an integrity check on open
- **THEN** the system SHALL exit with a message naming the file and the
  `qf db repair` command, and SHALL NOT silently recreate it — the same file
  holds user-authored state from 0003 onward, so discarding it is data loss

### Requirement: Data quality is checked on ingest

Every observation passes validation before it is cached, so a bad row is caught
at the boundary rather than discovered as an impossible Sharpe ratio.

#### Scenario: Structural validation
- **WHEN** a provider returns a frame
- **THEN** `validate_price_frame` SHALL reject a duplicated date, a
  non-monotonic index, a non-positive price, or a non-finite value that is not
  `NaN`
- **AND** the rejection SHALL name the symbol, date, and rule

#### Scenario: Implausible moves are flagged
- **WHEN** a single-day return exceeds a configurable threshold, defaulting to
  50%
- **THEN** the observation SHALL be kept, and a WARNING SHALL be logged naming
  the symbol, date, and move
- **AND** the frame's `attrs["flags"]` SHALL record it, so downstream reporting
  can surface it beside any result that used it

#### Scenario: Adjustment consistency
- **WHEN** adjusted and unadjusted closes are both available
- **THEN** the adjustment factor SHALL be monotone non-increasing going back in
  time for a series with only splits and dividends
- **AND** a violation SHALL be flagged, since it indicates a provider data error

### Requirement: Corporate actions and history

#### Scenario: Adjusted close is total return
- **WHEN** `field="adj_close"` is used
- **THEN** the series SHALL reflect splits and cash dividends, so differencing
  it yields total return
- **AND** the output SHALL state "total return" where adjusted data was used
  and "price return" where it was not

#### Scenario: Delisted and renamed tickers
- **WHEN** a ticker no longer trades
- **THEN** the provider SHALL return its history up to the last quote rather
  than an empty frame, where the source retains it
- **AND** the frame's `attrs` SHALL record the last quote date and, if known,
  the reason

#### Scenario: Survivorship is stated, not hidden
- **WHEN** any backtest or optimization runs on a user-supplied ticker list
- **THEN** the output SHALL note that a list chosen today reflects survivors,
  and results over past windows are biased upward for that reason
- **AND** the tool SHALL NOT claim to correct for it, since no free source
  provides point-in-time constituents

### Requirement: Missing data has a policy, never a default

#### Scenario: Gaps are classified
- **WHEN** a date is missing from a series
- **THEN** the data layer SHALL classify it as: market closed, instrument not
  yet listed, instrument delisted, or provider gap
- **AND** only a provider gap SHALL be eligible for filling

#### Scenario: Filling is explicit
- **WHEN** a caller wants provider gaps filled
- **THEN** it SHALL choose `drop`, `ffill`, or `raise` via a parameter with no
  default, per the rule in `portfolio-optimization`
- **AND** the count of filled observations SHALL be reported in `attrs`

#### Scenario: Alignment reports what it dropped
- **WHEN** `align_frames(how="inner")` removes dates
- **THEN** the count and the reason per source SHALL be recorded in the result's
  `attrs`, and reported at INFO

#### Scenario: Too little data is an error, not a shorter answer
- **WHEN** after alignment fewer observations remain than the calling method's
  declared minimum
- **THEN** `InsufficientDataError` SHALL be raised naming the count, the
  minimum, and which source constrained the window
- **AND** the computation SHALL NOT proceed on a silently shortened window

### Requirement: Offline test suite

The full test suite SHALL pass with no network access.

#### Scenario: CI run
- **WHEN** `pytest -m "not network"` runs with networking disabled
- **THEN** every test SHALL pass using recorded fixtures under `tests/fixtures/`
