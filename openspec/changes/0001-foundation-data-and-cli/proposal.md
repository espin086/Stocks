---
change: 0001-foundation-data-and-cli
milestone: v1 (part 1 of 2)
depends_on: []
status: implemented
---

# 0001 — Foundation: data layer and CLI shell

## Outcome

Someone with a fresh `pip install sobres` and **no API keys** can run:

```bash
pip install sobres
sobres init          # configure keys and storage, interactively; ends by running doctor
sobres doctor        # every check actionable; exit 0 means it works
sobres data prices AAPL MSFT NVDA --start 2015-01-01 --format table
```

…and get clean tabular output, cached locally, with the second run served from
disk in well under a second.

## Why

Every other milestone consumes prices, factor returns, or macro series. Building
them one-off inside each feature is how tools rot: four copies of a date-alignment
bug, four different notions of "adjusted close." This change puts a single typed
boundary in front of all market data and a single CLI shell in front of all
commands, so 0002–0005 are pure math plus a thin command file each.

It also sets the architectural precedent (`core` / `data` / `cli` separation) while
the codebase is small enough that the rule is free to follow.

## What changes

- **New capability `market-data`** — provider protocols, a yfinance price provider,
  a FRED macro provider, a Ken French factor provider, and a cache with
  per-dataset TTL and sub-range reuse.
- **New capability `storage`** — repository protocols and a backend registry, so
  the database is reachable only through a port. SQLite is the first adapter, not
  the interface. A shared conformance suite defines what "a supported backend"
  means, and the schema stays inside the capability intersection of SQLite,
  PostgreSQL, and DuckDB.
- **New capability `observability`** — structured logging on by default and
  OpenTelemetry tracing behind an optional extra, instrumenting the adapters and
  the I/O layer while `core/` stays pure.
- **New capability `onboarding`** — `sobres init`, `sobres doctor`, `sobres upgrade`, and a
  settings registry they all derive from. Every configurable value is declared
  once; init prompts for it, doctor checks it, `sobres config` accepts it, and the
  0004 settings page renders it. Doctor's checks are a registry too, and a test
  asserts every setting and provider has one.
- **New capability `command-registry`** — every command declared once with a
  pydantic parameter model and a typed result; the Typer CLI is generated from
  it. 0004 later derives the HTTP API and UI forms from the same declarations,
  which is why it lands here and not there.
- **New capability `testing`** — the test taxonomy, what each kind may depend
  on, and the architecture and invariant suites that every later "a test SHALL
  assert" refers to.
- **Data quality** (in `market-data`) — validation on ingest, corporate-action
  consistency, a missing-data policy with no default, and survivorship stated
  in output rather than hidden.
- **New capability `currency`** — every monetary series declares its currency, an
  `FxProvider` with keyless ECB rates, typed `CurrencyPair` so rate direction
  cannot be got wrong, and one explicit conversion operation. The FX and PPP
  analytics are 0010; only the model that makes them possible lands here.
- **New capability `cli-shell`** — root Typer app, `--format table|json|csv`,
  `-v/-vv` and `--log-format`, a config resolution chain, uniform error handling,
  and the `sobres data` / `sobres cache` command groups.
- `src/sobres/config.py` — settings from env → config file → defaults.
- Test fixtures: recorded provider payloads under `tests/fixtures/` so the whole
  suite runs offline.

## Non-goals

- No optimization, factor regression, forecasting, or goal math. That is 0002+.
- No paid providers (Polygon/Tiingo/FMP). The protocols are designed to admit one
  later; no adapter is written now.
- **No second storage backend is implemented.** The port, the registry, and the
  conformance suite ship; PostgreSQL and DuckDB adapters do not. An abstraction
  with one implementation is a guess — but a guess made cheap to correct, which
  is the point of shipping the conformance suite alongside it.
- No metrics pipeline. Logs and traces only; counters and histograms can be
  derived from spans if they are ever wanted.
- **No FX or PPP analytics.** Decomposition, hedging, and purchasing-power
  comparison are 0010. This change ships the currency *model* only, for the same
  reason timezone handling is settled at the data boundary: retrofitting it after
  0002 computes returns would mean revisiting every risk and optimization
  function.
- No FastAPI surface. The layering keeps the door open; the door stays shut.
- No survivorship-bias-free or point-in-time fundamentals. yfinance cannot give
  that, and pretending otherwise would be worse than the limitation.

## Risks

| Risk | Mitigation |
|---|---|
| yfinance is an unofficial, breakage-prone API | Isolate behind `PriceProvider`; pin a known-good version; contract tests against recorded fixtures catch shape drift |
| Ken French CSVs have irregular, multi-table layouts | Parser is its own tested unit with a checked-in sample; fail loudly on unexpected structure rather than silently mis-slicing |
| Cached data goes stale mid-analysis | Per-dataset TTL, `sobres cache info` shows age, `--refresh` forces a re-fetch |
| One SQLite file becomes a single point of failure for user-authored state | 0003 adds `sobres db export` and a migration story; a corrupt database refuses to be silently recreated |
| Silent timezone/calendar misalignment across sources | One rule, enforced at the data boundary: all series are tz-naive dates on a trading-day index; alignment is an explicit, tested operation |
| The storage abstraction is designed around SQLite and leaks when a real second backend arrives | The schema is constrained to a documented three-way capability intersection now, not later; identifiers are application-generated; timestamps are explicit UTC; the conformance suite is written against the contract rather than against SQLite's behavior |
| Abstraction costs more than it saves for a single-user tool | The port is thin — repository protocols plus an expression layer — and no second adapter is built on speculation. If the second backend never arrives, the cost is a few protocol files |
| Logging leaks an API key | Key-name and URL redaction at the formatter, applied to logs and span attributes alike, asserted by a test that runs every command with a sentinel credential at DEBUG |
| Instrumentation changes behavior or output | A test asserts stdout is byte-identical across log levels and with tracing on and off |
| A rate is applied in the wrong direction | Direction is carried by `CurrencyPair(base, quote)`, call sites never touch a raw rate, and round-trip conversion is a test |
| A listing quoted in a sub-unit (GBp, ZAc) is read as the major unit | The data layer normalizes to the major unit and a test covers a real pence-quoted listing — a silent hundred-fold error otherwise |
| A later milestone adds an API key or provider and forgets to make it configurable or diagnosable | Settings and checks are registries; a test asserts every env var the code reads is a declared setting and every setting and provider has a doctor check |
| `sobres init` hangs a container or CI on a prompt | `--non-interactive` takes values from flags and environment only and exits 3 naming any missing required value |
| Doctor hangs on a dead network | Every network check has a five-second cap and `--offline` skips them; skipped is not failed |
| Hand-written commands in 0001 have to be rewritten when 0004 needs API and UI surfaces | The registry lands here; 0004 adds consumers of existing declarations rather than restructuring them |
| "A test SHALL assert" in later specs never becomes a test | The `testing` spec defines the suites and a scenario-coverage test that fails on an unreferenced scenario once a change is marked implemented |
| Bad provider rows produce plausible-looking wrong results | Validation on ingest; implausible moves flagged in `attrs` and surfaced beside results; missing-data handling requires an explicit policy |
| Currency support slows or complicates the single-currency path | No rate is fetched when every input shares a currency, and results are asserted identical to a build without conversion |
