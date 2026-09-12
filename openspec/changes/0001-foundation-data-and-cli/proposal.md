---
change: 0001-foundation-data-and-cli
milestone: v1 (part 1 of 2)
depends_on: []
status: proposed
---

# 0001 — Foundation: data layer and CLI shell

## Outcome

Someone with a fresh `pip install quantfolio` and **no API keys** can run:

```bash
qf data prices AAPL MSFT NVDA --start 2015-01-01 --format table
qf data factors --model ff5 --start 2015-01-01
qf cache info
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
  a FRED macro provider, a Ken French factor provider, and a SQLite-backed cache
  with per-dataset TTL and sub-range reuse.
- **New capability `cli-shell`** — root Typer app, `--format table|json|csv`,
  a config resolution chain, uniform error handling, and the `qf data` /
  `qf cache` command groups.
- `src/quantfolio/config.py` — settings from env → config file → defaults.
- Test fixtures: recorded provider payloads under `tests/fixtures/` so the whole
  suite runs offline.

## Non-goals

- No optimization, factor regression, forecasting, or goal math. That is 0002+.
- No paid providers (Polygon/Tiingo/FMP). The protocols are designed to admit one
  later; no adapter is written now.
- No FastAPI surface. The layering keeps the door open; the door stays shut.
- No survivorship-bias-free or point-in-time fundamentals. yfinance cannot give
  that, and pretending otherwise would be worse than the limitation.

## Risks

| Risk | Mitigation |
|---|---|
| yfinance is an unofficial, breakage-prone API | Isolate behind `PriceProvider`; pin a known-good version; contract tests against recorded fixtures catch shape drift |
| Ken French CSVs have irregular, multi-table layouts | Parser is its own tested unit with a checked-in sample; fail loudly on unexpected structure rather than silently mis-slicing |
| Cached data goes stale mid-analysis | Per-dataset TTL, `qf cache info` shows age, `--refresh` forces a re-fetch |
| One SQLite file becomes a single point of failure for user-authored state | 0003 adds `qf db export` and a migration story; a corrupt database refuses to be silently recreated |
| Silent timezone/calendar misalignment across sources | One rule, enforced at the data boundary: all series are tz-naive dates on a trading-day index; alignment is an explicit, tested operation |
