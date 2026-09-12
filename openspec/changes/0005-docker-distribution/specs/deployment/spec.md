# deployment — spec delta (0005)

## ADDED Requirements

### Requirement: One image, CLI entrypoint

#### Scenario: The CLI is the entrypoint
- **WHEN** the image runs with any arguments
- **THEN** they SHALL be passed to `qf`
- **AND** `docker run <image> --help` SHALL print the same help as a local install

#### Scenario: No container-only code path
- **WHEN** the image is built
- **THEN** it SHALL contain the same wheel published to PyPI for that version
- **AND** SHALL NOT contain a separate server entry point or container-specific
  application code

#### Scenario: Serving
- **WHEN** the image runs `serve --host 0.0.0.0`
- **THEN** the API and the built UI SHALL be served from one process on the
  configured port, defaulting to 8787

#### Scenario: One-off commands
- **WHEN** the image runs an analytical command instead of `serve`
- **THEN** it SHALL execute, write to the mounted database, and exit with the
  CLI's exit code

### Requirement: Data persistence in the container

#### Scenario: Database lives on a volume
- **WHEN** the image runs with no `QUANTFOLIO_DB_URL` set
- **THEN** the database SHALL be SQLite at `/data/quantfolio.db`
- **AND** `/data` SHALL be declared as a volume

#### Scenario: A missing volume fails loudly
- **WHEN** `/data` is not writable at startup
- **THEN** the container SHALL exit non-zero with a message naming the mount
- **AND** SHALL NOT fall back to a path inside the container layer, which would
  discard the user's data on `docker rm` with no warning

#### Scenario: Data survives replacement
- **WHEN** a container is removed and a new one started on the same volume
- **THEN** every saved portfolio, watchlist, goal, and run SHALL still be present

#### Scenario: Host and container share one database
- **WHEN** a host-side `qf` command and the container point at the same file
- **THEN** each SHALL see the other's writes, per 0003's portability requirement

### Requirement: Runtime security posture

#### Scenario: Non-root
- **WHEN** the container runs
- **THEN** it SHALL run as a non-root user with a fixed, documented uid and gid
- **AND** files it writes to a mounted volume SHALL be usable from the host

#### Scenario: No secrets in the image
- **WHEN** the published image is scanned
- **THEN** no API key, token, or credential SHALL be present in any layer
- **AND** this SHALL be asserted by a scan in the release pipeline, not by review

#### Scenario: Configuration at runtime only
- **WHEN** configuration is supplied
- **THEN** it SHALL come from environment variables or a mounted config file
- **AND** SHALL resolve by the same precedence the CLI uses in 0001

#### Scenario: Minimal runtime
- **WHEN** the image is built
- **THEN** the runtime stage SHALL contain neither the Node toolchain nor build
  tooling

#### Scenario: Health
- **WHEN** the image is running `serve`
- **THEN** a health endpoint SHALL report readiness
- **AND** the image SHALL declare a `HEALTHCHECK` against it

#### Scenario: Signals
- **WHEN** the container receives SIGTERM
- **THEN** it SHALL shut down cleanly within 10 seconds, finishing or recording
  any in-flight job rather than leaving it marked running forever

### Requirement: Image publishing

#### Scenario: Same gate as PyPI
- **WHEN** a version is published to PyPI by 0000's pipeline
- **THEN** the image SHALL be built and pushed in the same run, gated on the same
  version check and the same green CI

#### Scenario: Version parity is asserted
- **WHEN** the image is built for release
- **THEN** the version reported by `qf --version` inside it SHALL be asserted
  equal to the wheel version being published
- **AND** a mismatch SHALL fail the run before any push

#### Scenario: Tagging
- **WHEN** an image is pushed
- **THEN** it SHALL be tagged with the exact version, the minor series, and
  `latest`
- **AND** an existing exact-version tag SHALL never be overwritten

#### Scenario: Architectures
- **WHEN** an image is published
- **THEN** `linux/amd64` and `linux/arm64` SHALL both be available under one tag

#### Scenario: Provenance
- **WHEN** an image is published
- **THEN** a build attestation and an SBOM SHALL be attached, matching the
  provenance guarantee 0000 already makes for the wheel

#### Scenario: Credentials
- **WHEN** the pipeline authenticates to the registry
- **THEN** it SHALL use a scoped access token held as a repository secret, used by
  no other job
- **AND** publishing SHALL be disarmed by default, as PyPI publishing is, until
  explicitly enabled

#### Scenario: Size budget
- **WHEN** the image is built
- **THEN** the compressed runtime image SHALL be under 500 MB
- **AND** exceeding it SHALL fail the build

#### Scenario: Vulnerability scan
- **WHEN** an image is built for release
- **THEN** it SHALL be scanned, and a fixable high or critical finding SHALL fail
  the run, with the same named-exception discipline 0000 applies to `pip-audit`

### Requirement: Observability in the container

#### Scenario: Logs are the container's stream
- **WHEN** the container runs
- **THEN** logs SHALL go to stderr in JSON, since stderr is not a TTY there
- **AND** no log file SHALL be written inside the container by default, where it
  would grow unbounded in a layer nobody inspects

#### Scenario: Log level is configurable at runtime
- **WHEN** `QUANTFOLIO_LOG_LEVEL` is set in the environment
- **THEN** it SHALL take effect with no image rebuild

#### Scenario: Tracing is configured, not built in
- **WHEN** standard `OTEL_*` variables are supplied to the container
- **THEN** tracing SHALL activate, the image having the `otel` extra installed
- **AND** with those variables unset, tracing SHALL be inert

#### Scenario: An unreachable collector never breaks the container
- **WHEN** an exporter endpoint is configured but unreachable
- **THEN** the container SHALL start, serve, and pass its health check
- **AND** SHALL warn once rather than per span

### Requirement: The storage backend is a container concern too

#### Scenario: The default stays SQLite on a volume
- **WHEN** no `QUANTFOLIO_DB_URL` is supplied
- **THEN** the container SHALL use SQLite at `/data/quantfolio.db`

#### Scenario: An external backend needs no different image
- **WHEN** `QUANTFOLIO_DB_URL` names another registered backend
- **THEN** the same image SHALL use it without rebuild
- **AND** the `/data` volume SHALL become unnecessary, which
  `qf deploy check` SHALL report rather than leave implied

#### Scenario: A database URL is a secret
- **WHEN** a connection URL containing credentials is supplied
- **THEN** it SHALL be redacted in logs, spans, and every `qf deploy` output,
  under 0001's redaction rules

### Requirement: The CLI generates the deployment

#### Scenario: Compose generation
- **WHEN** `qf deploy compose` runs
- **THEN** a valid compose file SHALL print to stdout, with the image pinned to
  the running version, `/data` mounted, and the port published

#### Scenario: Generated from resolved configuration
- **WHEN** the compose file is generated
- **THEN** it SHALL reflect the configuration the CLI currently resolves, so a
  working local setup produces a matching deployment

#### Scenario: Secrets are referenced, never embedded
- **WHEN** the generated compose file needs an API key or token
- **THEN** it SHALL reference an environment variable by name
- **AND** SHALL NOT contain any secret value, since the output is a file people
  commit

#### Scenario: Preflight
- **WHEN** `qf deploy check` runs
- **THEN** it SHALL report the image and version, the resolved database path and
  whether it is writable, the bind address and port, whether a token is required
  and configured, and which credentials are present — naming each by key only

#### Scenario: Exposure is called out
- **WHEN** `qf deploy check` finds a non-loopback bind address with no token
- **THEN** it SHALL report this as an error, not a warning

#### Scenario: Environment template
- **WHEN** `qf deploy env` runs
- **THEN** a `.env` template SHALL print with every recognized variable, its
  default, and a one-line description
- **AND** values of existing secrets SHALL NOT be included

### Requirement: Documented deployment

#### Scenario: Quickstart is real
- **WHEN** the documented `docker run` command is executed on a clean machine
- **THEN** it SHALL produce a reachable, working UI
- **AND** the command SHALL be exercised in CI against the built image, so the
  documentation cannot rot

#### Scenario: Upgrades
- **WHEN** a user pulls a newer image against an existing volume
- **THEN** 0003's migrations SHALL run automatically on first open
- **AND** the documented upgrade path SHALL include taking a backup first
