# http-api — spec delta (0004)

## ADDED Requirements

### Requirement: Single command registry

Every capability SHALL be declared once and consumed by all three surfaces.

#### Scenario: One declaration
- **WHEN** a command is added to `quantfolio/registry.py` with its parameters,
  types, defaults, and help text
- **THEN** a CLI subcommand, an HTTP route, and an OpenAPI schema entry SHALL all
  exist for it without further code

#### Scenario: Parity is tested, not trusted
- **WHEN** the test suite runs
- **THEN** a test SHALL enumerate the registry and assert every entry has an HTTP
  route and a UI view registered against it
- **AND** the build SHALL fail if any entry lacks either

#### Scenario: Adding a parameter reaches every surface
- **WHEN** a parameter is added to a registered command
- **THEN** it SHALL appear as a CLI option, an API field, and a UI form control
- **AND** its default SHALL be identical in all three

#### Scenario: Types are declared once
- **WHEN** a parameter declares its type and constraints
- **THEN** the same pydantic model SHALL validate it for both the CLI and the API,
  so an invalid value is rejected identically by each

### Requirement: The API is an adapter, not a second implementation

#### Scenario: No business logic
- **WHEN** any module under `api/` is reviewed
- **THEN** it SHALL contain request handling, validation, and serialization only
- **AND** a test SHALL assert `api/**` performs no computation of its own, as is
  already enforced for `cli/**`

#### Scenario: Identical results
- **WHEN** the same operation is run through the CLI and through the API with
  identical parameters
- **THEN** the results SHALL be identical
- **AND** a test SHALL assert this for every registered command

### Requirement: Jobs for long-running work

#### Scenario: Work is dispatched, not awaited
- **WHEN** an optimization, backtest, or simulation is requested
- **THEN** the API SHALL persist a job record and return its id immediately
- **AND** the response SHALL be returned in under 200 ms regardless of the work

#### Scenario: Progress streams
- **WHEN** a client subscribes to a job's event stream
- **THEN** progress updates SHALL be delivered over SSE until the job reaches a
  terminal state

#### Scenario: Jobs survive a reload
- **WHEN** a client disconnects and reconnects to a running job
- **THEN** it SHALL receive the current state and continue streaming
- **AND** a completed job's result SHALL remain retrievable from the database

#### Scenario: Failure is reported, not swallowed
- **WHEN** a job raises
- **THEN** it SHALL end in a failed state carrying the error message and the
  exit-code class from 0001's taxonomy
- **AND** the UI SHALL render that message rather than a generic failure

#### Scenario: Cancellation
- **WHEN** a running job is cancelled
- **THEN** it SHALL stop at the next checkpoint and be recorded as cancelled
- **AND** partial results SHALL NOT be presented as complete

### Requirement: Access control

#### Scenario: Loopback by default
- **WHEN** `qf serve` runs with no `--host`
- **THEN** it SHALL bind `127.0.0.1` only
- **AND** no token SHALL be required, since the socket is not reachable remotely

#### Scenario: Non-local binding requires a token
- **WHEN** `--host` names any address other than a loopback address
- **THEN** a token SHALL be required
- **AND** if none is configured, one SHALL be generated, stored hashed, and
  printed once to stderr with an explicit warning about what exposure means

#### Scenario: Tokens are generated, never chosen
- **WHEN** a token is created
- **THEN** it SHALL come from a cryptographically secure source with at least 128
  bits of entropy
- **AND** a user-supplied weak token SHALL be rejected

#### Scenario: Tokens are stored hashed
- **WHEN** a token is persisted
- **THEN** only a salted hash SHALL be stored, and comparison SHALL be constant-time
- **AND** the plaintext SHALL never be written to the database or any log

#### Scenario: Unauthenticated requests
- **WHEN** a request arrives without a valid token while one is required
- **THEN** the response SHALL be 401 with no detail about what was wrong

#### Scenario: Rotation and revocation
- **WHEN** `qf serve token rotate` runs
- **THEN** a new token SHALL replace the old one and every existing session SHALL
  stop working

#### Scenario: Token never appears in a URL
- **WHEN** the token is transmitted
- **THEN** it SHALL travel in a header or an httpOnly cookie
- **AND** SHALL NOT be accepted as a query parameter, where proxies and browser
  history would record it

### Requirement: Observability across the request and job boundary

#### Scenario: Every request is a trace
- **WHEN** a request arrives
- **THEN** a span SHALL cover it, carrying the route, the registry command, and
  the response status
- **AND** a run id SHALL be bound to every log record produced while serving it

#### Scenario: Inbound trace context is honored
- **WHEN** a request carries W3C `traceparent`
- **THEN** the request's span SHALL be a child of that context, so the API
  appears inside a caller's trace rather than starting a disconnected one

#### Scenario: Context crosses into the job
- **WHEN** a request dispatches a job
- **THEN** the trace context and run id SHALL be persisted with the job record
- **AND** the job's execution span SHALL link to the request that created it,
  so work that outlives its request is still traceable to its origin

#### Scenario: The trace id reaches the client
- **WHEN** a response is returned
- **THEN** it SHALL carry the correlation id in a response header
- **AND** an error response SHALL include it in the body, so a user can quote it

#### Scenario: Job progress is not a log
- **WHEN** a job reports progress
- **THEN** it SHALL come from the optional progress callback 0001 defined
- **AND** the core computation SHALL remain free of logging and tracing imports

### Requirement: API hygiene

#### Scenario: Documented
- **WHEN** the server is running
- **THEN** OpenAPI docs SHALL be served, generated from the registry

#### Scenario: Errors carry the shared taxonomy
- **WHEN** a request fails
- **THEN** the response SHALL map 0001's error classes onto HTTP status codes
  (usage → 400, config/credential → 400 with guidance, provider → 502,
  insufficient data → 422, internal → 500)
- **AND** the body SHALL carry the same actionable message the CLI would print

#### Scenario: No stack traces to clients
- **WHEN** an unexpected error occurs
- **THEN** the client SHALL receive a generic message and a correlation id
- **AND** the detail SHALL go to the server log only

#### Scenario: CORS is closed by default
- **WHEN** no origins are configured
- **THEN** cross-origin requests SHALL be refused, since the SPA is served by the
  same origin and nothing legitimate needs otherwise

#### Scenario: Rate limiting on a reachable deployment
- **WHEN** the server is bound to a non-loopback address
- **THEN** authentication attempts SHALL be rate-limited per source address
