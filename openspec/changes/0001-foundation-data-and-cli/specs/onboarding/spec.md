# onboarding — spec delta (0001)

The user's path is three commands, and each later milestone has to keep it
three:

```
pip install quantfolio-cli
qf init        # configure everything configurable, interactively
qf doctor      # prove the install works, or say exactly what is wrong
```

## ADDED Requirements

### Requirement: Settings are declared once

Every configurable value SHALL be one declaration in `quantfolio/settings.py`,
the way every command is one declaration in the registry.

#### Scenario: Declaration shape
- **WHEN** a setting is declared
- **THEN** it SHALL carry a key, an environment variable name, a type, a
  default or `required`, whether it is a secret, a one-line description, a URL
  or instruction for obtaining it where applicable, and an optional live
  validator

#### Scenario: Four consumers, one source
- **WHEN** a setting exists in the registry
- **THEN** `qf init` SHALL prompt for it, `qf doctor` SHALL check it,
  `qf config set|show` SHALL accept it, and the 0004 settings page SHALL render
  it, with no per-surface code

#### Scenario: A milestone cannot add an unconfigurable key
- **WHEN** the test suite runs
- **THEN** a test SHALL assert that every environment variable the code reads
  corresponds to a declared setting
- **AND** SHALL assert that every declared setting has a doctor check

### Requirement: `qf init`

#### Scenario: Guided, in the terminal
- **WHEN** `qf init` runs in a TTY
- **THEN** it SHALL walk the settings registry in order, showing each setting's
  description and where to obtain it, and prompt for a value
- **AND** secrets SHALL be entered without echo

#### Scenario: Idempotent and re-runnable
- **WHEN** `qf init` runs against an existing configuration
- **THEN** it SHALL show each current value — secrets masked to their last four
  characters — and offer to keep or replace it
- **AND** re-running with no changes SHALL leave the configuration byte-identical

#### Scenario: Optional settings can be skipped
- **WHEN** a setting is not required
- **THEN** the prompt SHALL accept an empty answer and state what will not work
  without it, naming the commands affected

#### Scenario: Live validation with consent
- **WHEN** a setting declares a live validator and the user provides a value
- **THEN** `qf init` SHALL offer to verify it with one request, and report the
  result
- **AND** a failed verification SHALL let the user retry, keep the value anyway,
  or skip — never silently store a key that just failed

#### Scenario: Storage is set up
- **WHEN** `qf init` completes
- **THEN** the database SHALL exist at the resolved URL with migrations applied,
  and the config file SHALL be written at mode `0600`
- **AND** the paths of both SHALL be printed

#### Scenario: Non-interactive mode
- **WHEN** `qf init --non-interactive` runs
- **THEN** values SHALL be taken from flags and environment only, with no prompt
- **AND** a missing required value SHALL exit 3 naming it, so scripts and
  containers fail clearly rather than hang on a prompt

#### Scenario: Ends with proof
- **WHEN** `qf init` completes
- **THEN** it SHALL run `qf doctor` and print the result
- **AND** SHALL print one runnable first command tailored to what was
  configured, so the next step is a copy-paste rather than a search

#### Scenario: First-run hint
- **WHEN** any command runs and no configuration exists
- **THEN** stderr SHALL carry a one-line hint to run `qf init`
- **AND** the command SHALL still proceed if it needs nothing that is missing —
  the hint is a hint, not an error

### Requirement: `qf doctor`

#### Scenario: Checks are declared, like commands and settings
- **WHEN** a diagnostic exists
- **THEN** it SHALL be a registered `Check` with a name, a category, a `run`
  returning ok / warn / fail with a message, and an optional idempotent `fix`
- **AND** a milestone that adds a provider, a setting, or a runtime dependency
  SHALL register a check for it in the same change

#### Scenario: What is checked in 0001
- **WHEN** `qf doctor` runs
- **THEN** it SHALL check at least: Python version; installed quantfolio version
  and whether a newer release exists; the installer in use; config file presence,
  parseability, and `0600` permissions; every declared setting; database URL
  resolution, reachability, writability, and schema version against the code;
  cache size and staleness; each provider's reachability; which extras are
  installed; and free disk space at the database path

#### Scenario: Every line is actionable
- **WHEN** a check does not pass
- **THEN** its line SHALL state what is wrong and the exact command or action
  that fixes it
- **AND** a check SHALL never report a failure without a next step

#### Scenario: Output
- **WHEN** `qf doctor` runs in a TTY
- **THEN** it SHALL render one line per check with a status glyph, grouped by
  category, and a one-line summary
- **AND** `--format json` SHALL emit the full structured result for scripting

#### Scenario: Exit code
- **WHEN** `qf doctor` completes
- **THEN** it SHALL exit 0 if no check failed, and 1 if any did
- **AND** warnings SHALL not affect the exit code unless `--strict` is given

#### Scenario: Offline
- **WHEN** `--offline` is given, or the network is unreachable
- **THEN** network-dependent checks SHALL report as skipped, not failed
- **AND** every network check SHALL have a timeout of at most five seconds, so
  doctor never hangs

#### Scenario: Safe automatic repair
- **WHEN** `qf doctor --fix` runs
- **THEN** every registered fix SHALL be attempted — creating the config
  directory, correcting file permissions, applying pending migrations, clearing a
  corrupt cache entry — and each SHALL be reported as applied or not applicable
- **AND** no fix SHALL create, change, or delete a secret; those go through
  `qf init` or `qf config set`

#### Scenario: Secrets never appear
- **WHEN** `qf doctor` reports on a secret setting
- **THEN** it SHALL show presence and validity only, never the value, in any
  output format

#### Scenario: One implementation of health
- **WHEN** 0005's `qf deploy check` or the container `HEALTHCHECK` needs to
  assess the install
- **THEN** it SHALL run doctor's checks rather than its own

### Requirement: `qf upgrade`

#### Scenario: Installer is detected, not assumed
- **WHEN** `qf upgrade` runs
- **THEN** it SHALL detect whether quantfolio was installed by pip, pipx, uv, or
  is running in the container, and SHALL print the exact upgrade command for
  that installer

#### Scenario: Confirmation before acting
- **WHEN** an upgrade command is about to run
- **THEN** the user SHALL be asked to confirm, and `--yes` SHALL skip the prompt
- **AND** `--check` SHALL only report whether a newer version exists

#### Scenario: Post-upgrade migration
- **WHEN** an upgrade completes
- **THEN** the next `qf` invocation SHALL apply any pending migrations per 0003,
  after the automatic backup that spec requires

### Requirement: Onboarding is tested end to end

#### Scenario: The three-command path is a test
- **WHEN** CI's build job runs
- **THEN** it SHALL install the built wheel into a clean environment, run
  `qf init --non-interactive`, run `qf doctor --offline`, and assert exit 0
- **AND** it SHALL then run one data command against a recorded fixture and
  assert output

#### Scenario: Time to first result
- **WHEN** a new user follows the README
- **THEN** the path from `pip install` to a first rendered result SHALL require
  no more than the three commands above and no reading beyond their own output
