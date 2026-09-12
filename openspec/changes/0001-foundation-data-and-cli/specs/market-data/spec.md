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

### Requirement: On-disk cache

The system SHALL cache every provider response to disk, keyed by a content hash of
the request parameters.

#### Scenario: Cache hit
- **WHEN** an identical request is made within the dataset's TTL
- **THEN** the response SHALL be served from disk without a network call
- **AND** the call SHALL complete in under 1 second for a 10-ticker, 10-year frame

#### Scenario: Forced refresh
- **WHEN** any command is invoked with `--refresh`
- **THEN** the cache SHALL be bypassed and the fresh response written back

#### Scenario: Cache location
- **WHEN** no override is configured
- **THEN** the cache SHALL live in the platform user-cache dir via `platformdirs`
- **AND** SHALL be overridable by `QUANTFOLIO_CACHE_DIR`

#### Scenario: Corrupt cache entry
- **WHEN** a cached parquet file fails to read
- **THEN** the system SHALL delete the entry, re-fetch, and warn on stderr — not fail

### Requirement: Offline test suite

The full test suite SHALL pass with no network access.

#### Scenario: CI run
- **WHEN** `pytest -m "not network"` runs with networking disabled
- **THEN** every test SHALL pass using recorded fixtures under `tests/fixtures/`
