# cli-shell — spec delta (0001)

## ADDED Requirements

### Requirement: Root command and entry points

The system SHALL expose a Typer application as both `sobres` and `sobres`.

#### Scenario: Version
- **WHEN** `sobres --version` runs
- **THEN** the installed version SHALL print to stdout and exit 0

#### Scenario: Bare invocation
- **WHEN** `sobres` runs with no arguments
- **THEN** help SHALL print and exit 0 (not an error)

#### Scenario: Command groups
- **WHEN** `sobres --help` runs
- **THEN** the listed groups SHALL be exactly those shipped so far, each with a
  one-line description

### Requirement: Uniform output formatting

Every command that emits data SHALL support `--format table|json|csv`.

#### Scenario: Default is human-readable
- **WHEN** `--format` is omitted and stdout is a TTY
- **THEN** output SHALL be a Rich table

#### Scenario: Piping is machine-readable by default
- **WHEN** stdout is not a TTY and `--format` is omitted
- **THEN** output SHALL be CSV, so `sobres data prices AAPL > p.csv` just works

#### Scenario: JSON is parseable and complete
- **WHEN** `--format json` is used
- **THEN** stdout SHALL contain only a single valid JSON document
- **AND** all human-facing chrome (progress bars, warnings) SHALL go to stderr

#### Scenario: Float precision
- **WHEN** rendering a table
- **THEN** prices SHALL show 2 decimals, returns and weights 4, and t-statistics 2
- **AND** `--format json` SHALL emit full precision, unrounded

### Requirement: Configuration resolution

Settings SHALL resolve in strict precedence: CLI flag → environment variable →
config file → built-in default.

#### Scenario: Config file location
- **WHEN** no override is set
- **THEN** the config file SHALL be `<user-config-dir>/sobres/config.toml`

#### Scenario: Setting a key
- **WHEN** `sobres config set fred_api_key ABC123` runs
- **THEN** the key SHALL persist to the config file with mode `0600`

#### Scenario: Secrets are never echoed
- **WHEN** `sobres config show` runs
- **THEN** any key whose name contains `key`, `token`, or `secret` SHALL render as
  its last 4 characters prefixed by `****`

### Requirement: Error handling and exit codes

The CLI SHALL never surface an unhandled traceback for an anticipated failure.

#### Scenario: Exit code contract
- **WHEN** a command fails
- **THEN** the exit code SHALL be: `1` unexpected internal error, `2` bad usage,
  `3` missing configuration or credential, `4` provider/network failure,
  `5` insufficient data for the requested computation

#### Scenario: Actionable messages
- **WHEN** any error with code 3, 4, or 5 is raised
- **THEN** the message SHALL state what failed and the next action to take

#### Scenario: Debug escape hatch
- **WHEN** `--debug` is passed
- **THEN** the full traceback SHALL print to stderr in addition to the message

### Requirement: `sobres data` command group

The CLI SHALL expose the data layer directly, so users can inspect the inputs to
every later calculation.

#### Scenario: Prices
- **WHEN** `sobres data prices AAPL MSFT --start 2020-01-01 --end 2020-12-31` runs
- **THEN** a date-indexed table with `AAPL` and `MSFT` columns SHALL print

#### Scenario: Macro
- **WHEN** `sobres data macro DGS10 CPIAUCSL --start 2020-01-01` runs
- **THEN** a date-indexed table of those FRED series SHALL print

#### Scenario: Factors
- **WHEN** `sobres data factors --model ff5 --frequency monthly` runs
- **THEN** a date-indexed table of the FF5 factors plus `RF` SHALL print

### Requirement: `sobres cache` command group

#### Scenario: Inspect
- **WHEN** `sobres cache info` runs
- **THEN** total size on disk, entry count, and oldest entry age SHALL print

#### Scenario: Clear
- **WHEN** `sobres cache clear` runs
- **THEN** the user SHALL be prompted to confirm before any deletion
- **AND** `--yes` SHALL skip the prompt for scripted use

### Requirement: Not-advice disclaimer

#### Scenario: Report-style output
- **WHEN** any command emits an analysis or a recommendation-shaped result in
  `table` format
- **THEN** a footer SHALL read
  `For research and education only. Not investment advice.`
- **AND** the footer SHALL be omitted from `json` and `csv` output so it cannot
  corrupt machine parsing
