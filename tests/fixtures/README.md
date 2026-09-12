# Recorded provider payloads

Every provider is tested offline against the files here, parsed by the same
code path the live source feeds. `scripts/record_fixtures.py` regenerates
them from the live providers; re-recording is a deliberate, reviewable diff in
its own commit.

**Current state (0001):** the environment that implemented 0001 had no route
to Yahoo Finance, FRED, the ECB or the Ken French Data Library, so these files
were produced by `scripts/synthesize_fixtures.py` in each vendor's exact payload
shape — columns, separators, preambles, the `"."` missing marker, the
multi-table CSV layout — with seeded random-walk values. Each `meta.json` says
`recorded_at: null` and `synthesized_at: <timestamp>` so nobody mistakes them
for market data. The one exception is the first Fama-French monthly row (July
1926), which carries the published values so the known-month regression test
asserts a real number.

Run `python scripts/record_fixtures.py` with network access (and
`--fred-api-key` for FRED) to replace them with live recordings.

| Directory | Shape | Source of truth |
|---|---|---|
| `yfinance/` | `Ticker.history(auto_adjust=False)` CSV + `meta.json` currency; `fundamentals.json` holds the `Ticker.info` keys `analyze stock` reads (0007) | yfinance 1.7 |
| `fred/` | `fred/series/observations?file_type=json` body | FRED API |
| `ecb/` | `EXR/D.<CCY>.EUR.SP00.A?format=csvdata` body | ECB Data Portal |
| `ken_french/` | the CSV inside `<file>_CSV.zip` | Ken French Data Library |
