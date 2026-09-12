# command-registry — spec delta (0001)

Every command is declared once. In 0001 the registry drives only the CLI; 0004
derives the HTTP API and UI forms from the same declarations. It lives here so
that 0004 adds surfaces rather than rewriting commands.

## ADDED Requirements

### Requirement: One declaration per command

#### Scenario: Declaration shape
- **WHEN** a command is registered
- **THEN** it SHALL declare a dotted name (`data.prices`, `optimize.markowitz`),
  a one-line help string, a pydantic parameter model, a result type, and a
  handler that accepts the parameter model and returns the result type
- **AND** the handler SHALL be the only place the command's adapter logic lives

#### Scenario: The CLI is generated
- **WHEN** the Typer application is built
- **THEN** every registered command SHALL become a subcommand under its group,
  with options generated from the parameter model's fields, types, defaults,
  and descriptions
- **AND** no command SHALL be added to the Typer app by hand

#### Scenario: Help text has one source
- **WHEN** a parameter's help is shown anywhere
- **THEN** it SHALL come from the field description in the parameter model

#### Scenario: Defaults have one source
- **WHEN** a parameter is omitted on any surface
- **THEN** the default applied SHALL be the parameter model's default
- **AND** a test SHALL assert that no generated surface introduces a default of
  its own

### Requirement: Parameter models are the validation layer

#### Scenario: Validation before the handler
- **WHEN** invalid input reaches any surface
- **THEN** the parameter model SHALL reject it before the handler runs
- **AND** the message SHALL name the field and the constraint

#### Scenario: Shared types
- **WHEN** a parameter is a ticker list, a date, a currency, a frequency, a
  weight vector, or an objective
- **THEN** it SHALL use the shared type for it, so its parsing, validation, and
  rendering are identical across every command

#### Scenario: Cross-field rules live in the model
- **WHEN** a constraint spans fields — weights must match tickers in count and
  sum to one; `--portfolio` and `--tickers` are mutually exclusive
- **THEN** it SHALL be a model validator, not handler code
- **AND** it SHALL therefore apply identically on every surface

### Requirement: Results are typed

#### Scenario: Result types are frozen dataclasses or pydantic models
- **WHEN** a handler returns
- **THEN** its result SHALL be a declared type, never a bare `DataFrame` or dict
- **AND** the type SHALL carry the provenance the renderers need — estimators,
  data window, currency, disclaimer applicability

#### Scenario: Rendering is generic
- **WHEN** a result is rendered as table, JSON, or CSV
- **THEN** one renderer SHALL handle every result type via its declared shape
- **AND** no command SHALL format its own output

### Requirement: Introspection

#### Scenario: The registry is queryable
- **WHEN** `qf commands --format json` runs
- **THEN** every registered command SHALL be listed with its group, name, help,
  and parameter schema
- **AND** this SHALL be the source the parity tests in 0004 enumerate

#### Scenario: Registration is complete at import
- **WHEN** `quantfolio.registry` is imported
- **THEN** every command SHALL be registered
- **AND** a test SHALL assert the count against an explicit list, so a command
  module that fails to import is caught rather than silently absent

### Requirement: Stability

#### Scenario: Names are an interface
- **WHEN** a command or parameter is renamed
- **THEN** the old name SHALL remain as a deprecated alias for one minor version
  with a warning on use
- **AND** a test SHALL cover the alias

#### Scenario: Adding a parameter is backward compatible
- **WHEN** a parameter is added to an existing command
- **THEN** it SHALL have a default, so every existing invocation still works
