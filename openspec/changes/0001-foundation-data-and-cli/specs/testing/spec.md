# testing — spec delta (0001)

Every later spec says "a test SHALL assert". This defines what kinds of tests
exist, where they live, and what each is allowed to depend on — so those
assertions are enforceable rather than aspirational.

## ADDED Requirements

### Requirement: Test taxonomy

The suite SHALL be organized by what each test proves, not by module.

#### Scenario: Kinds and their locations
- **WHEN** a test is added
- **THEN** it SHALL live under exactly one of:
  `tests/core/` (pure math against known answers),
  `tests/data/` (providers against recorded fixtures, storage conformance),
  `tests/cli/` (surface behavior through the registry),
  `tests/architecture/` (import and layering rules),
  `tests/invariants/` (properties that must hold across every command),
  `tests/network/` (live provider contracts, marked `network`)

#### Scenario: Markers are declared
- **WHEN** pytest runs
- **THEN** `--strict-markers` SHALL be on, and the only markers SHALL be
  `network` and `slow`
- **AND** CI SHALL run with `-m "not network"`; `slow` runs everywhere

### Requirement: Math is tested against known answers

#### Scenario: Sources of truth
- **WHEN** a `core/` function is tested
- **THEN** expected values SHALL come from one of: a hand computation shown in
  the test, a textbook example with citation, a closed-form solution, or a
  checked-in fixture produced by an independent implementation (such as the R
  reference in `legacy_code/`)
- **AND** a test SHALL NOT assert against a value the function itself produced

#### Scenario: Tolerances are explicit and justified
- **WHEN** a floating-point comparison is made
- **THEN** the tolerance SHALL be stated and SHALL NOT exceed `1e-6` relative
  unless the test names the numerical reason

#### Scenario: Edge cases are enumerated
- **WHEN** a core function is tested
- **THEN** it SHALL be exercised on: the minimum viable input, a single
  observation where meaningful, `NaN` under each declared policy, and the
  degenerate case its spec names (singular covariance, zero variance, empty
  overlap)

### Requirement: Architecture is tested, not reviewed

#### Scenario: Layering rules are code
- **WHEN** `tests/architecture/` runs
- **THEN** it SHALL assert by import scanning that: `core/` imports no network,
  database, logging, or tracing module; `cli/` and `api/` import no numerical
  library for computation; database drivers appear only under
  `data/storage/adapters/`; no module outside `data/currency.py` multiplies or
  divides by an exchange rate

#### Scenario: Literals that must not exist
- **WHEN** `tests/architecture/` runs
- **THEN** it SHALL fail on a bare periods-per-year literal (`252`, `12`, `52`)
  in annualization code outside `core/conventions.py`

#### Scenario: Every scenario has a test
- **WHEN** the suite runs
- **THEN** a test SHALL parse every `#### Scenario:` heading in the archived and
  active specs and assert a test references it by name
- **AND** an unreferenced scenario SHALL fail the build once its change is
  marked implemented

### Requirement: Fixtures, not mocks, at the data boundary

#### Scenario: Recorded payloads
- **WHEN** a provider is tested offline
- **THEN** it SHALL parse a real payload recorded under `tests/fixtures/` by
  `scripts/record_fixtures.py`
- **AND** the fixture SHALL carry the date and provider version it was recorded
  from

#### Scenario: Re-recording is deliberate
- **WHEN** a fixture is regenerated
- **THEN** it SHALL be a reviewable diff in its own commit, never an incidental
  change

#### Scenario: Provider drift is caught, not guessed
- **WHEN** `pytest -m network` runs
- **THEN** each provider's live response SHALL be checked against the shape the
  offline fixture was recorded with
- **AND** a shape change SHALL fail with a message naming the fixture to
  re-record

### Requirement: Conformance and parity suites

#### Scenario: Conformance suites are parametrized
- **WHEN** more than one implementation of a protocol exists or is planned
- **THEN** a single shared suite SHALL be parametrized over a fixture list of
  implementations, and adding one SHALL mean adding to that list only

#### Scenario: Suites that must exist
- **WHEN** the plan is implemented
- **THEN** conformance suites SHALL exist for `PriceProvider`, `MacroProvider`,
  `FactorProvider`, `FxProvider`, and every storage repository protocol
- **AND** a parity suite SHALL exist for CLI/API/UI from 0004

### Requirement: Invariants across every command

#### Scenario: Enumerated, not sampled
- **WHEN** an invariant test runs
- **THEN** it SHALL iterate the registry, so a new command is covered the moment
  it is registered

#### Scenario: Required invariants
- **WHEN** `tests/invariants/` runs
- **THEN** for every registered command it SHALL assert: `--format json` yields
  one parseable document at DEBUG logging; stdout is byte-identical across log
  levels and with tracing on and off; a sentinel credential appears nowhere in
  stderr; the same inputs produce identical output on two runs; the disclaimer
  footer is present in table output and absent from JSON and CSV for
  report-style results

### Requirement: Property-based tests where they earn their place

#### Scenario: Round-trip properties
- **WHEN** a function has an inverse — currency conversion, serialization,
  rate inversion, migration up from a fixture
- **THEN** a property test SHALL assert the round-trip over generated inputs

#### Scenario: Algebraic properties
- **WHEN** a function has a known identity — return decomposition reconciling
  to the total, weights summing to one, frontier volatility non-decreasing in
  return
- **THEN** a property test SHALL assert it over generated inputs
- **AND** generated inputs SHALL be constrained to the function's valid domain
  so failures are real, not artifacts of nonsense input

### Requirement: Coverage and speed

#### Scenario: Coverage floor
- **WHEN** CI runs
- **THEN** line and branch coverage SHALL be at least 90% and SHALL NOT fall
  from one merge to the next

#### Scenario: Offline suite is fast
- **WHEN** `pytest -m "not network"` runs on a developer machine
- **THEN** it SHALL complete in under two minutes
- **AND** any test over five seconds SHALL carry the `slow` marker and a comment
  saying why
