# packaging — spec delta (0011)

## ADDED Requirements

### Requirement: One name across every surface

The distribution, import package, console script, and environment prefix SHALL all
be `sobres`, and no artifact SHALL carry the former `quantfolio` or `qf` naming.

#### Scenario: Installing
- **WHEN** a user runs `pip install sobres`
- **THEN** the distribution `sobres` SHALL install
- **AND** exactly one console script SHALL be created, named `sobres`
- **AND** the importable package SHALL be `sobres`

#### Scenario: No residual old name
- **WHEN** the repository is searched case-insensitively for `quantfolio`, or for
  `qf` as a whole word
- **THEN** there SHALL be no match outside `CHANGELOG.md`

#### Scenario: Environment variables
- **WHEN** the settings registry is enumerated
- **THEN** every declared environment variable SHALL begin with `SOBRES_`

### Requirement: Old names fail loudly, never silently

Where a user's environment or filesystem still carries the former naming, the tool
SHALL refuse to guess: it SHALL stop or report, name the replacement, and never
migrate data on its own.

#### Scenario: A stale environment variable
- **WHEN** any `QUANTFOLIO_*` environment variable is set
- **THEN** the process SHALL refuse to start
- **AND** the error SHALL name the `SOBRES_*` variable that replaces it

#### Scenario: A legacy data directory
- **WHEN** `sobres doctor` runs and a `quantfolio` config or data directory exists
- **THEN** the check SHALL report actionable
- **AND** SHALL print the exact command to move the directory
- **AND** SHALL NOT move, copy, or delete any file itself

### Requirement: The rename changes no behavior

The rename SHALL be a pure identifier change. No computed value, output format, or
test fixture SHALL differ because of it.

#### Scenario: Identical results
- **WHEN** any command runs against the same cached inputs and seed before and
  after the rename
- **THEN** stdout SHALL be byte-identical apart from the program name
- **AND** every test fixture value SHALL be unchanged
