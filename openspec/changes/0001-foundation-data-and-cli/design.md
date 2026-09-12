# 0001 — Design

## Layering

```
qf data prices AAPL
      │
      ▼
cli/commands/data.py ──► data/yfinance_provider.py ──► data/cache.py
      │                          │                          │
      │                          └─ network (only here)      ▼
      │                                          data/storage/base.py   ← port
      ▼                                                      │
cli/render.py  (table | json | csv)          adapters/sqlite.py  ← only place
      │                                                             a driver is
      └─ stdout: results only          logs + spans: stderr/exporter   imported
```

`core/` is untouched by this change — it has nothing to compute yet. That is the
point: the boundaries exist before there is pressure to cross them.

## Storage: a port, not a database

Two protocols and a registry:

```python
class KeyValueStore(Protocol): ...      # config-ish rows
class ObservationStore(Protocol):       # the cache, in domain terms
    def upsert_observations(self, rows: Sequence[Observation]) -> int: ...
    def read_observations(self, q: ObservationQuery) -> pd.DataFrame: ...
    def fetched_ranges(self, key: SeriesKey) -> list[DateRange]: ...
```

Note what the port speaks: observations and date ranges, not `SELECT`. A port
phrased in SQL is a SQL port, and swapping it is then a rewrite. Phrased in the
domain, a DuckDB or Postgres adapter is a new file and a fixture-list entry.

**`QUANTFOLIO_DB_URL` selects the adapter**, defaulting to
`sqlite:///<user-data-dir>/quantfolio.db`. Nothing above the adapter knows which
backend is live.

### The library underneath

**SQLAlchemy Core — the expression language, not the ORM.** It is the dialect
abstraction that already exists, tested against every backend worth naming, and
it lets one set of statements run on all three candidates. The ORM is still
declined for the reason the original spec gave: the schema is small, and object
mapping would hide the migration story that matters here.

SQLAlchemy sits *below* the repository protocols, not at the boundary. Call sites
never see a `Session`, a `Table`, or a `Row`. That keeps even this choice
reversible: replacing it means rewriting the adapters, not the callers.

Alembic drives migrations for the same reason — one migration set, applied by the
adapter, since DDL transaction semantics differ between backends.

### The capability intersection

The schema stays inside what SQLite, PostgreSQL, and DuckDB all do identically:

| Constraint | Why |
|---|---|
| Portable column types only | SQLite's dynamic typing will accept anything; Postgres will not |
| Application-generated ids | Autoincrement and sequence semantics differ in all three |
| Explicit UTC timestamps | Each handles local time differently; storing UTC removes the question |
| JSON as text | Native JSON types and operators differ; the application encodes and decodes |
| No backend-specific SQL in shared code | Anything unexpressible portably becomes a named adapter method that every adapter implements |

**Only SQLite is implemented.** The registry, the port, and the conformance suite
ship; the other adapters do not. This is a deliberate middle position: building
Postgres support now would be speculative work, and building no abstraction would
make it expensive later. The conformance suite is the part that makes the
difference — it states the contract in executable form while there is exactly one
implementation and no ambiguity about what the contract *is*.

## Observability

Structured logging always on (default WARNING); tracing behind an extra.

**stderr, always.** `--format json` must stay a single parseable document on
stdout at any log level. This is the requirement everything else bends around.

**The purity tension, resolved.** `core/` performs no I/O, and a log line is I/O.
The resolution is that instrumentation lives in the adapters:

```python
# cli/commands/optimize.py — the adapter observes the call
with tracer.start_as_current_span("optimize.markowitz", attributes=attrs):
    log.info("optimizing", objective=obj, n_assets=len(mu))
    result = core.optimize(mu, sigma, objective=obj)   # pure, silent
    log.info("optimized", elapsed=..., sharpe=result.sharpe)
```

The timings and parameters this records are the adapter's observation of the
call, which is what anyone reading the trace actually wants. For computations
long enough to need intermediate visibility — a backtest's rebalance loop — the
core function takes an **optional progress callback**, and the caller decides
whether that becomes a log line, a span event, or (in 0004) a job progress
update. The computation stays pure; with no callback, nothing changes.

**Redaction at the formatter**, not at call sites. Relying on every future author
to remember not to log a key is relying on the wrong thing. A test runs every
command with a sentinel credential at DEBUG and asserts the sentinel appears
nowhere in stderr.

**OpenTelemetry API, SDK optional.** The API ships a no-op implementation, so an
ordinary install carries no tracing dependency and no measurable overhead, and
the instrumentation calls are the same code either way. Standard `OTEL_*`
variables activate it with no flag. An unreachable exporter warns once and never
fails the command — observability that can break the tool is a liability.

**Assumption-laden results log at WARNING**, not INFO: a fallback risk-free rate,
a repaired covariance matrix, a shifted backtest start. These are the lines that
explain a surprising number, so they surface by default.

## Provider protocols

`typing.Protocol`, not ABCs. Providers are plain classes; nothing inherits. This
keeps a future paid adapter (Polygon, Tiingo) a drop-in, and keeps test doubles to
a few lines.

```python
class PriceProvider(Protocol):
    name: str
    def get_prices(
        self,
        tickers: Sequence[str],
        start: date,
        end: date | None = None,
        field: PriceField = "adj_close",
    ) -> pd.DataFrame: ...
```

A shared `contract_test_price_provider(provider)` helper is parametrized over every
registered provider, so adding a provider means adding one line to a fixture list.

## The canonical frame

Every disagreement about "what is a price series" is settled once, here:

- index: `DatetimeIndex`, name `date`, **tz-naive**, ascending, no duplicates
- columns: ticker symbols, uppercase, in the order requested
- values: `float64`, `NaN` for genuinely missing observations
- `frame.attrs`: `{"field": ..., "provider": ..., "fetched_at": ...}`

`attrs` survives most pandas operations and gives every downstream report its
provenance line for free.

**Adjusted close is the default and the recommendation.** Total-return math on
unadjusted closes is the single most common silent error in amateur portfolio
tools — a 2-for-1 split reads as a −50% day. Raw OHLC stays available via `field`
for anyone who knows they want it.

## Cache

One SQLite file, holding observations rather than opaque blobs:

```sql
observation(provider, dataset, symbol, date, value, ...)  -- PK on all four keys
fetch_log(provider, dataset, symbol, range_start, range_end, fetched_at, ttl)
```

**Why SQLite rather than a directory of cached response files.** A
content-addressed blob cache keys on the exact request, so asking for
2015–2024 after caching 2015–2025 is a cache miss and a second download of data
already on disk. Storing observations instead makes any sub-range free and any
extension a fetch of only the missing tail — which is the common case, since
every new day's run extends yesterday's range by one bar.

It also settles the deployment question before it is asked: 0003 puts saved
portfolios and goals in this same file, and 0005 mounts it as a single Docker
volume. One file is the whole of the tool's state, backed up by copying it.

`fetch_log` is what makes TTL meaningful: it records which *ranges* were
actually requested, so the system can tell "no data exists for these dates" from
"these dates were never fetched" — a distinction a row-presence check cannot
make, and the reason a naive cache re-downloads market holidays forever.

TTL by dataset, reflecting how often the underlying data actually changes:

| Dataset | TTL | Why |
|---|---|---|
| Daily prices, ended in the past | 30 days | Historical bars are immutable in practice |
| Daily prices, running to today | 1 day | Today's bar moves |
| FRED series | 1 day | Most series update daily-to-monthly |
| Ken French factors | 7 days | Published monthly, with revisions |

The TTL is stored per entry, so changing a default never invalidates history
already on disk.

## Error taxonomy

One base, narrow leaves, each mapped to an exit code:

```
QuantfolioError                 → 1
├── UsageError                  → 2
├── ConfigurationError          → 3   (missing key, bad config file)
├── ProviderError               → 4   (network, upstream shape change)
│   └── UnknownTickerError
└── InsufficientDataError       → 5   (fewer observations than the method needs)
    └── AlignmentError
```

`InsufficientDataError` exists now, before any math does, because it is the error
0002–0005 will raise constantly (a covariance matrix needs more observations than
assets; a factor regression needs enough months to be meaningful). Defining it here
means those changes inherit the exit-code contract rather than inventing one.

## CLI output

Rendering is one function — `render(frame_or_model, fmt, stream)` — so no command
formats anything itself. TTY detection picks the default: a Rich table for humans,
CSV when piped. Rich's box-drawing in a pipe is the kind of small thing that makes
a tool feel unusable in a script.

Everything that is not the result — progress, warnings, the disclaimer — goes to
stderr or is suppressed in machine formats. `qf data prices AAPL --format json | jq`
must never need a `grep -v`.

## Testing

- **Fixtures, not mocks, at the boundary.** Real provider payloads recorded once and
  checked into `tests/fixtures/`. Tests parse the real thing; when a vendor changes
  its shape, a `network`-marked contract test run manually catches it, and the fixture
  is re-recorded deliberately.
- **The cache is tested against a temp dir**, including the corrupt-entry path —
  a cache that can wedge a user's install is a support burden forever.
- **`pytest -m "not network"` is the CI gate.** Live tests exist and are runnable
  (`pytest -m network`), but a third party's outage never turns this repo red.

## Alternatives considered

| Choice | Rejected alternative | Why |
|---|---|---|
| Typer | Click (as in `fire-calculator`) | Type hints become the parser, which matches a `mypy --strict` codebase; Typer is Click underneath, so nothing is lost |
| Protocol | ABC base class | Providers share no implementation; inheritance would only add ceremony |
| SQLite cache | Parquet blob cache | Sub-range reuse and incremental extension; one file for the whole deployment; the same store 0003 and 0005 build on |
| `attrs` for provenance | A wrapper class | Keeps the return type plain `DataFrame`, so pandas knowledge transfers directly |
| Repository port in domain terms | A port phrased as SQL execution | A SQL-shaped port is a SQL port; swapping the backend would still be a rewrite |
| SQLAlchemy Core below the port | Hand-written SQL per adapter | One statement set across three dialects; hand-written SQL per backend is the cost the abstraction exists to avoid |
| SQLAlchemy Core | SQLAlchemy ORM | Object mapping would hide the migration story, which is the part that has to stay legible |
| Ship the port with one adapter | Build Postgres now, or build no abstraction | Speculative work versus expensive retrofit; the conformance suite is what makes the middle position hold |
| Instrument adapters | Instrument `core/` | Preserves purity, and adapter-observed timings are what a trace reader wants |
| OTel API with optional SDK | Always-on tracing, or none | Zero dependency and zero overhead by default, same call sites either way |
| structlog | stdlib `logging` alone | Typed key/value context and bound scopes; still routes third-party stdlib records through one handler |
