# 0004 — Design

## The registry, one level down

0001 declares every command once and generates the CLI from it. This change adds
two more consumers of the same declarations:

```
                    registry.py
                         │
        ┌────────────────┼──────────────────┐
        ▼                ▼                  ▼
   cli/ (Typer)     api/ (FastAPI)     frontend/ (React)
   options from     routes from        forms from
   param model      param model        OpenAPI schema
        │                │                  │
        └────────────────┴──────────────────┘
                         │
                 same handler, same result type
```

A command is `Command(name, help, params: type[BaseModel], result: type,
handler)`. From that:

| Surface | Generated | Mechanism |
|---|---|---|
| CLI | `qf <group> <name> --field ...` | Typer options from `params.model_fields` |
| API | `POST /api/v1/<group>/<name>` | FastAPI route with `params` as the body model |
| OpenAPI | schema entry | FastAPI, for free |
| UI | form + result view | TypeScript types generated from OpenAPI; a form renderer keyed on field type |

**Why POST for everything, including reads.** Parameter models carry ticker
lists, date ranges, and weight vectors; encoding those in query strings would
mean a second serialization the CLI does not have. One body model, one
validation path, one set of error messages. The UI is behind a token, not a
public REST API, so resource-style verbs buy nothing here.

**Why the UI's types come from OpenAPI rather than being hand-written.** The
generated client is committed; CI regenerates it and fails on a diff. An API
change that would break the UI therefore breaks the build, not the user.

## Parity as a test

```python
@pytest.mark.parametrize("command", registry.all())
def test_every_command_has_a_route(command, app): ...

@pytest.mark.parametrize("command", registry.all())
def test_every_command_has_a_view(command, frontend_manifest): ...
```

The frontend build emits a manifest of which registry names it renders a view
for. The second test reads it. Adding a command without a view fails Python CI,
not a frontend review.

## Long-running work

Optimizations and backtests can run for seconds to minutes. The rule is that no
HTTP request waits on a computation.

```
POST /api/v1/optimize/backtest   →  202 { job_id }        (< 200 ms)
GET  /api/v1/jobs/{id}           →  { state, progress, result? }
GET  /api/v1/jobs/{id}/events    →  text/event-stream
POST /api/v1/jobs/{id}/cancel
```

The job record lives in 0003's `jobs` repository, so it survives a server
restart and a page reload. A single in-process worker drains a queue; the
process is single-user, so one worker is the right number and avoids every
concurrency question a pool would raise.

**Progress comes from the core function's optional callback** (0001
observability design), which the job runner turns into an event and a row
update. `core/` still emits nothing itself.

SSE over websockets: one direction is all that is needed, it works through every
proxy, and reconnection is a browser primitive rather than a protocol to write.

## Access model

| Bind address | Token |
|---|---|
| loopback (default) | not required — the socket is unreachable remotely |
| anything else | required; generated if absent; printed once with a warning |

Tokens are 32 random bytes, base64url, stored as a salted hash, compared in
constant time. Presented as a bearer header by the CLI and the generated client,
and set as an httpOnly cookie by the SPA after a one-time paste — never in a
query string, where proxies and browser history would keep it.

There is deliberately no login page in the sense of a username field. The token
authenticates *the deployment*. Multi-user is out of scope, and a fake account
model would be the first thing a later multi-user change had to remove.

## Frontend

```
frontend/
├── src/
│   ├── api/           # generated client + types; regenerated in CI
│   ├── forms/         # one renderer per field type, keyed off the schema
│   ├── views/         # one per registry group; results + charts
│   ├── charts/        # ECharts wrappers with theme tokens
│   └── theme/         # tokens shared with site/ (0006)
└── manifest.json      # registry names this build renders — read by the parity test
```

Built assets are copied into the wheel at `quantfolio/api/static/` by the
release pipeline. `pip install quantfolio-cli[web]` therefore needs no Node; only
a contributor changing `frontend/` does.

**The equivalent command is always shown.** Every form renders the `qf` command
line it would run, live. The UI is a way of learning the CLI, not a replacement
for it — and it keeps the two surfaces honest with each other in the user's eyes,
not just in the test suite.

## Alternatives considered

| Choice | Rejected alternative | Why |
|---|---|---|
| Registry from 0001 | Hand-written Typer commands, registry added in 0004 | Would mean rewriting every command here; adding surfaces to declarations is cheap, retrofitting declarations onto surfaces is not |
| POST for every command | REST resources | One body model matches the CLI's one parameter model; no second serialization |
| Generated TypeScript client | Hand-written API types | Drift becomes a build failure instead of a runtime one |
| Single in-process worker | Worker pool, Celery, RQ | Single-user process; one worker answers every concurrency question by construction |
| SSE | WebSockets | One direction suffices; proxies and reconnection are solved problems |
| Deployment token | User accounts | Multi-user is out of scope; a fake account model is debt |
| Frontend manifest for parity | Trusting the view list | Parity must fail Python CI, where the registry is |
