# observability — spec delta (0001)

Structured logging always; distributed tracing when asked for. Both instrument
the adapters and the I/O layer, never the pure math.

## ADDED Requirements

### Requirement: Logs never contaminate output

The most important property: a logging system that corrupts `--format json` is
worse than no logging.

#### Scenario: stdout is results only
- **WHEN** anything is logged, at any level
- **THEN** it SHALL be written to stderr
- **AND** stdout SHALL carry only the command's result

#### Scenario: Machine output stays parseable
- **WHEN** a command runs with `--format json` at any log level
- **THEN** stdout SHALL remain a single valid JSON document
- **AND** a test SHALL assert this with logging at its most verbose setting

### Requirement: Structured logging

#### Scenario: Every record is structured
- **WHEN** a log record is emitted
- **THEN** it SHALL carry a timestamp, level, logger name, message, and typed
  key/value context — not an interpolated string

#### Scenario: Human and machine renderings
- **WHEN** stderr is a TTY
- **THEN** records SHALL render human-readably with aligned keys and colour
- **AND** when stderr is not a TTY, or `--log-format json` is given, each record
  SHALL be one JSON object per line

#### Scenario: Levels
- **WHEN** verbosity is set
- **THEN** `-v` SHALL select INFO, `-vv` DEBUG, `--log-level` an explicit level,
  and `QUANTFOLIO_LOG_LEVEL` the same via environment
- **AND** the default SHALL be WARNING, so ordinary runs are quiet

#### Scenario: Levels mean something specific
- **WHEN** a level is chosen for a record
- **THEN** ERROR SHALL mean the operation failed, WARNING SHALL mean the result
  is still returned but is degraded or assumption-laden, INFO SHALL mean a
  significant step completed, and DEBUG SHALL mean detail for diagnosis
- **AND** an assumption that changes a number — a fallback risk-free rate, a
  repaired covariance matrix, a shifted backtest start — SHALL be at least
  WARNING, because it is exactly what a user needs to see

#### Scenario: Correlation
- **WHEN** any command or request begins
- **THEN** a run id SHALL be generated and attached to every record it produces
- **AND** that id SHALL appear in the final error message when one occurs, so a
  user can quote it

#### Scenario: Context accumulates
- **WHEN** work enters a nested scope — a provider fetch, a solve, a rebalance
- **THEN** that scope's identifying context SHALL bind to every record within it
  without being passed explicitly to each call

### Requirement: Secrets never reach a log or a span

#### Scenario: Redaction
- **WHEN** a value is logged whose key contains `key`, `token`, `secret`,
  `password`, or `authorization`
- **THEN** it SHALL be replaced with a redaction marker
- **AND** this SHALL apply to log records, span attributes, and exception
  context alike

#### Scenario: Secrets in URLs
- **WHEN** a URL containing credentials is logged
- **THEN** the credentials SHALL be stripped before the record is emitted
- **AND** a test SHALL assert that a FRED request URL carrying an API key never
  appears in full at any level, including DEBUG

#### Scenario: Enforced by test
- **WHEN** the test suite runs
- **THEN** a test SHALL exercise every command with a sentinel credential
  configured and DEBUG logging on, and assert the sentinel appears nowhere in
  captured stderr

### Requirement: What gets logged

#### Scenario: Provider calls
- **WHEN** the data layer serves a request
- **THEN** it SHALL log at DEBUG the provider, dataset, symbols, date range,
  whether it was a cache hit, miss, or partial extension, rows returned, and
  elapsed time

#### Scenario: Storage
- **WHEN** a storage operation runs
- **THEN** it SHALL log at DEBUG the operation, affected row count, and elapsed
  time
- **AND** a statement exceeding a configurable slow threshold SHALL log at
  WARNING

#### Scenario: Computation boundaries
- **WHEN** an adapter invokes a core computation
- **THEN** it SHALL log at INFO the operation, its resolved parameters, and
  elapsed time on completion

#### Scenario: Failures carry cause
- **WHEN** an error is logged
- **THEN** the record SHALL carry the exception type, the error class from 0001's
  taxonomy, and the traceback at DEBUG
- **AND** a handled-and-recovered condition SHALL be logged where it is handled,
  not silently swallowed

### Requirement: Tracing

#### Scenario: OpenTelemetry, opt-in
- **WHEN** tracing is used
- **THEN** it SHALL use the OpenTelemetry API
- **AND** the SDK SHALL be an optional install (`quantfolio-cli[otel]`), with the
  API's no-op implementation active by default so an ordinary install carries no
  tracing dependency and no measurable overhead

#### Scenario: Enabling
- **WHEN** the standard `OTEL_*` environment variables configure an exporter
- **THEN** tracing SHALL activate with no code or flag change
- **AND** if the SDK is absent while those variables are set, the system SHALL
  warn once naming the extra to install, and continue

#### Scenario: Spanned operations
- **WHEN** tracing is active
- **THEN** spans SHALL cover the CLI command or HTTP request, each provider
  fetch, each cache lookup, each storage operation, each core computation
  invoked from an adapter, and each job execution

#### Scenario: Span attributes
- **WHEN** a span is recorded
- **THEN** it SHALL carry the attributes that make it diagnosable — provider and
  cache outcome for a fetch, row counts for a query, asset count and objective
  for a solve — subject to the same redaction as logs

#### Scenario: Failed spans
- **WHEN** an operation inside a span raises
- **THEN** the span SHALL be marked with error status and record the exception

#### Scenario: Logs and traces correlate
- **WHEN** tracing is active and a record is logged inside a span
- **THEN** the record SHALL carry the trace and span ids
- **AND** the run id SHALL remain present, so records correlate with or without
  tracing enabled

#### Scenario: Never fatal
- **WHEN** the exporter is unreachable, slow, or misconfigured
- **THEN** the command SHALL still complete and return its result
- **AND** the failure SHALL be reported once at WARNING, not per span

### Requirement: Instrumentation respects the architecture

The purity rule and observability appear to conflict: `core/` performs no I/O,
and emitting a log or a span is I/O. The conflict is resolved by where
instrumentation sits, not by weakening either rule.

#### Scenario: Core stays pure
- **WHEN** any module under `core/` is reviewed
- **THEN** it SHALL NOT import a logging or tracing library
- **AND** a test SHALL assert this alongside the existing checks that `core/`
  performs no network or database I/O

#### Scenario: Adapters instrument the calls they make
- **WHEN** an adapter invokes a core computation
- **THEN** the adapter SHALL open the span and emit the logs around that call
- **AND** the timing and parameters recorded SHALL be the adapter's observation
  of the call, which is what a reader of the trace wants anyway

#### Scenario: Long computations report progress without logging
- **WHEN** a core computation is long enough to need intermediate visibility —
  a backtest's rebalance loop, a Monte Carlo simulation
- **THEN** it SHALL accept an optional progress callback
- **AND** the caller SHALL decide whether that becomes a log line, a span event,
  or a job progress update, keeping the computation itself free of I/O
- **AND** with no callback supplied, behavior SHALL be unchanged

#### Scenario: Instrumentation does not change results
- **WHEN** the same command runs at WARNING and at DEBUG, with and without
  tracing active
- **THEN** stdout SHALL be byte-identical
- **AND** a test SHALL assert this, so observability can never alter a number

### Requirement: Configuration and operation

#### Scenario: Precedence
- **WHEN** logging or tracing is configured
- **THEN** it SHALL resolve through 0001's chain: flag, environment, config file,
  default

#### Scenario: Optional file sink
- **WHEN** a log file is configured
- **THEN** records SHALL be written there as JSON in addition to stderr, with
  size-based rotation and a bounded retention count

#### Scenario: Third-party noise is controlled
- **WHEN** a dependency emits its own log records
- **THEN** they SHALL be routed through the same handler and default to WARNING,
  so `yfinance` chatter does not appear at INFO
