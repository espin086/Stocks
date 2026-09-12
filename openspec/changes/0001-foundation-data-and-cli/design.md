# 0001 — Design

## Layering

```
qf data prices AAPL
      │
      ▼
cli/commands/data.py ──► data/yfinance_provider.py ──► data/cache.py ──► disk
      │                          │
      │                          └─ network (only here)
      ▼
cli/render.py  (table | json | csv)
```

`core/` is untouched by this change — it has nothing to compute yet. That is the
point: the boundary exists before there is pressure to cross it.

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

Content-addressed parquet:

```
<cache_dir>/<provider>/<sha256(canonical_request_json)[:16]>.parquet
<cache_dir>/<provider>/<same>.meta.json   # request, fetched_at, ttl, rows
```

Parquet because it round-trips dtypes and the `DatetimeIndex` exactly — CSV does
not, and a cache that silently changes dtypes is worse than no cache.

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
| Parquet cache | SQLite / CSV | Exact dtype and index round-trip; columnar reads; no schema migrations |
| `attrs` for provenance | A wrapper class | Keeps the return type plain `DataFrame`, so pandas knowledge transfers directly |
