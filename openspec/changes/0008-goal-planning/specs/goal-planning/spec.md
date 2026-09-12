# goal-planning — spec delta (0008)

## ADDED Requirements

### Requirement: Real vs. nominal is always explicit

#### Scenario: Mode selection
- **WHEN** any `sobres plan` command runs
- **THEN** `--real` or `--nominal` SHALL determine whether returns and targets are
  inflation-adjusted
- **AND** the default SHALL be `--real`, because a retirement target in nominal
  dollars is meaningless

#### Scenario: Labeling
- **WHEN** any monetary result is displayed
- **THEN** it SHALL be labeled `(today's dollars)` or `(nominal)` accordingly

#### Scenario: Inflation source
- **WHEN** `--real` is active and no `--inflation` is supplied
- **THEN** trailing 10-year CPI (FRED `CPIAUCSL`) SHALL be used, and the rate and
  its window SHALL be stated in the output
- **AND** if FRED is unavailable, `2.5%` SHALL be used with a stderr note

### Requirement: Generic funding solver

The system SHALL solve for any one unknown among target, time, contribution, and
return, given the other three.

#### Scenario: Solve for time
- **WHEN** target, current balance, contribution, and return are supplied
- **THEN** the number of periods to reach the target SHALL be returned
- **AND** if the target is unreachable (contribution and return both non-positive
  relative to the gap), `InsufficientDataError` SHALL be raised saying so plainly

#### Scenario: Solve for contribution
- **WHEN** target, current balance, horizon, and return are supplied
- **THEN** the required periodic contribution SHALL be returned

#### Scenario: Contribution timing
- **WHEN** a contribution schedule is applied
- **THEN** `--timing end` (ordinary annuity, the default) or `--timing begin`
  (annuity-due) SHALL control whether the period's contribution earns that period's
  return

#### Scenario: Over-specified input
- **WHEN** all four of target, time, contribution, and return are supplied
- **THEN** `UsageError` SHALL be raised naming which one to omit

### Requirement: Retirement / FIRE planning

#### Scenario: FI number
- **WHEN** `sobres plan retire --expenses 90000` runs
- **THEN** the FI number SHALL be `annual_expenses / withdrawal_rate`, defaulting to
  a `0.04` withdrawal rate
- **AND** the output SHALL state the rate used and name its origin

#### Scenario: Savings rate and date
- **WHEN** income, expenses, current portfolio, and return are supplied
- **THEN** the output SHALL include the savings rate, the FI number, years to FI,
  and the projected FI date

#### Scenario: Coast FI
- **WHEN** `--coast` is supplied
- **THEN** the balance that would grow to the FI number by the target age with **no
  further contributions** SHALL be reported, along with whether it is already met

#### Scenario: Parity with the prior implementation
- **WHEN** the ported `savings_rate`, `fi_number`, and `project` functions run
- **THEN** results SHALL match `espin086/fire-calculator`'s test fixtures exactly

### Requirement: Named goal specializations

#### Scenario: House
- **WHEN** `sobres plan house --price 950000 --down-pct 0.20 --by 2029-06-01` runs
- **THEN** the down-payment target, required monthly saving, and whether the supplied
  `--monthly` meets it SHALL be reported
- **AND** if `--price-growth` is supplied, the target SHALL grow with it, because a
  house price rising faster than savings is the actual risk

#### Scenario: Car
- **WHEN** `sobres plan car --price 45000 --by 2027-01-01` runs
- **THEN** the required monthly saving SHALL be reported, with `--depreciation`
  optionally reporting expected resale value at a later date

#### Scenario: Education
- **WHEN** `sobres plan education --annual-cost 35000 --years 4 --starting 2038` runs
- **THEN** the total inflated cost and required monthly saving SHALL be reported
- **AND** education-cost inflation SHALL default to `5%`, separately from CPI, with
  the assumption stated

### Requirement: Monte Carlo and bootstrap simulation

#### Scenario: Simulation is run by default
- **WHEN** any `sobres plan` command runs
- **THEN** a simulation SHALL run and a success probability SHALL be reported
- **AND** `--simulate 0` SHALL disable it for a purely deterministic answer

#### Scenario: Reported distribution
- **WHEN** a simulation completes
- **THEN** the 10th, 25th, 50th, 75th, and 90th percentile outcomes SHALL be
  reported alongside the success probability

#### Scenario: The deterministic path is labeled
- **WHEN** both a deterministic projection and a simulation are shown
- **THEN** the deterministic figure SHALL be labeled as the median case, not as
  "the" answer

#### Scenario: Bootstrap mode
- **WHEN** `--method bootstrap` is supplied
- **THEN** returns SHALL be resampled in blocks from actual historical return
  sequences, preserving autocorrelation and sequence-of-returns risk
- **AND** the historical window used SHALL be stated

#### Scenario: Reproducibility
- **WHEN** `--seed` is supplied
- **THEN** repeated runs SHALL produce identical results
- **AND** the seed used SHALL be printed even when auto-generated, so any run can
  be reproduced

#### Scenario: Not advice
- **WHEN** any `sobres plan` command emits table output
- **THEN** the not-investment-advice footer SHALL be present
- **AND** the output SHALL state that taxes are not modeled and inputs are assumed
  after-tax
