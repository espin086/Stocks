---
change: 0004-web-ui
milestone: v1.2
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization, 0003-local-persistence]
status: implemented
planning_depth: proposal + 2 spec deltas + design + tasks
---

# 0004 — Web UI

## Outcome

```bash
sobres open                       # starts the server if needed, opens the browser
sobres open doctor                # straight to a view: settings, doctor, runs, run 42, ...
sobres serve                      # http://127.0.0.1:8787, no browser
sobres serve --host 0.0.0.0 --port 8787   # prints a token; required to bind non-local
```

A dark, fast single-page app with **every CLI capability** behind a form: pick or
build a portfolio, optimize it, drag along the efficient frontier, run a
walk-forward backtest and watch it progress, and read the full run history from
0003. Nothing in the UI that the CLI cannot do, and nothing in the CLI the UI
cannot reach.

## Why

The CLI is the right interface for someone who already knows what
`--objective max-sharpe --max-weight 0.35` means. Everything this tool computes is
also visual — an efficient frontier is a *curve*, a drawdown is a *shape*, a
correlation matrix is a *heatmap*. Reading those as ASCII tables discards most of
the information.

It also makes the tool demonstrable. The landing page in 0006 needs something to
show, and "watch the frontier solve" is the demo.

## What changes

- **New capability `http-api`** — FastAPI app at `sobres/api/`, a thin adapter
  over `core` and `data` exactly like `cli/`, holding no business logic.
- **New capability `web-ui`** — React + TypeScript SPA under `frontend/`, built to
  static assets and served by the same process.
- **Two new consumers of the command registry.** 0001 declares every command
  once and generates the CLI from it; this change generates the HTTP API and the
  UI's forms from the same declarations. This is what makes "the UI has all the
  features of the CLI" a tested invariant rather than an intention — and why the
  registry landed in 0001 rather than here: adding consumers to declarations is
  a generator each; retrofitting declarations onto hand-written commands would
  have been a rewrite of every one.
- **Job execution** — optimizations and backtests run as jobs persisted through
  0003's repositories, with progress streamed over SSE. Trace context and run id
  are persisted with the job, so work that outlives its request stays traceable.
- `sobres serve` as the entry point and `sobres open` as the one-command path from
  terminal to browser; `[web]` extra for FastAPI and uvicorn.

## The parity problem, and how it is solved

"A UI with all the features of the CLI" decays the moment someone adds a CLI flag
and forgets the form field. Three ways to prevent it, and only one survives
contact with a year of feature work:

| Approach | Why it fails |
|---|---|
| Write the UI to match the CLI, carefully | Drifts on the first hurried PR |
| Generate the UI from the OpenAPI schema | Fixes API↔UI drift but not CLI↔API drift, which is the one that matters |
| **One registry; CLI, API and UI all derive from it** | Adding a parameter in one place makes it appear in all three, and a parity test fails the build if any command lacks a route or a view |

The registry is the design decision this whole change rests on. Everything else is
presentation.

## Non-goals

- **No multi-user accounts.** One deployment is one person (see the access model).
  A shared token authenticates *the deployment*, not a user.
- No account recovery, email, or password flows — there are no passwords.
- No mobile-native app. The SPA is responsive; that is the extent of it.
- No server-side rendering or SEO. This is a tool behind a token, not a website;
  0006 is the public-facing page.
- No websocket bidirectional protocol. Jobs stream one way; SSE is sufficient and
  survives proxies that websockets do not.
- No charting of anything the CLI cannot compute. The UI visualizes results; it
  never becomes a second place where analysis logic lives.

## Risks

| Risk | Mitigation |
|---|---|
| Business logic leaks into the API or the frontend | The registry forces every operation through a `core` call; an import-inspection test asserts `api/**` imports no `scipy`/`numpy` computation helpers of its own, matching the rule already enforced for `cli/**` |
| The UI drifts from the CLI | A parity test enumerates the registry and fails if any command lacks an API route or a UI view |
| Exposing the UI on a LAN exposes someone's financial data | Binding a non-loopback address requires a token; the token is generated, not chosen; requests without it get 401; the first run prints an explicit warning about what exposure means |
| A long backtest ties up a request and times out behind a proxy | Work runs as a job; the request returns an id immediately; progress streams over SSE and survives a page reload because state is in the database |
| A Node build step makes the Python package hard to build | Built assets are committed to the wheel at release time by the pipeline, so `pip install` needs no Node; only contributors touching the frontend need it |
| Animation and chart libraries bloat the bundle | A hard bundle budget is a CI gate, not a guideline |
