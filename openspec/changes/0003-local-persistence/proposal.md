---
change: 0003-local-persistence
milestone: v1.1
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization]
status: proposed
---

# 0003 — Local persistence

## Outcome

Work stops being disposable. Portfolios, watchlists, goals and every analysis run
are saved and recallable, from the CLI now and from the UI in 0004:

```bash
qf portfolio save core --tickers AAPL MSFT NVDA JNJ --weights 0.3 0.3 0.2 0.2
qf optimize markowitz --portfolio core --save-run
qf run list --limit 20
qf run show 42 --format json
qf db info
qf db export --to ~/backups/quantfolio-2026-09-12.sqlite
```

## Why

0002 makes the tool useful; this makes it *cumulative*. Re-typing eight tickers
and a constraint set on every invocation is the difference between a demo and
something used weekly.

It is also the prerequisite for everything after it. The UI in 0004 needs saved
state to show and a job table to report progress from; the Docker deployment in
0005 needs exactly one thing to mount as a volume. Building those on ad-hoc files
would mean two storage stories to reconcile later.

0001 already established the single SQLite file. This change turns it from a
cache into a database: schema versioning, migrations, and the application tables.

## What changes

- **New capability `persistence`.**
- `data/db.py` grows a forward-only migration runner keyed on `schema_version`,
  applied automatically on open.
- `data/store/` — repositories for portfolios, watchlists, goals, analysis runs
  and job records. Plain data in, plain data out; no math, matching 0001's rule
  that `data/**` performs I/O and `core/**` performs computation.
- **New CLI groups** `qf portfolio`, `qf watchlist`, `qf run`, and `qf db`.
- `--save-run` on the analytical commands; `--portfolio <name>` accepted wherever
  `--tickers` is, so saved state substitutes for typing.

## Non-goals

- **No multi-user data model.** One database is one person's data. Adding a
  `user_id` column "just in case" would shape every query for a use case that is
  explicitly out of scope (see 0004's access model).
- No cloud sync, no remote database backends. Postgres is not on the roadmap;
  the single-file property is the point.
- No ORM. The schema is small and hand-written SQL keeps the migration story
  legible.
- No automatic scheduled refresh of saved portfolios. That is a cron job the user
  writes with the CLI they already have.
- No encryption at rest. The file holds public market data and the user's own
  ticker lists; a keyed database would add a lost-password failure mode for no
  real confidentiality gain. API keys stay in the config file at mode `0600`,
  never in the database.

## Risks

| Risk | Mitigation |
|---|---|
| A migration corrupts real user data | Forward-only, tested against fixture databases at every prior schema version; automatic timestamped backup before any migration; `qf db export` for a manual copy first |
| Schema churn during 0004 and 0005 makes migrations painful early | Version from the first release; treat every shipped schema as immutable even pre-1.0, since the cost of the discipline is far below the cost of a user's lost portfolios |
| CLI and server write concurrently and one wedges | WAL plus a busy timeout from 0001; writes are short transactions; the job table is the only hot row and is written by a single worker |
| The database grows without bound as price history accumulates | `qf db info` reports size by table; `qf cache clear` prunes cached observations while leaving user-authored rows untouched — the two must never be conflated |
| Saved runs reference market data that later gets revised | A run records the inputs and the resolved parameters it used, so it stays interpretable; it is a record of an analysis, not a promise of reproducibility against a mutable index |
