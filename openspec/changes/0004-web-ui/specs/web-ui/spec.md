# web-ui — spec delta (0004)

## ADDED Requirements

### Requirement: Stack

#### Scenario: Chosen libraries
- **WHEN** the frontend is built
- **THEN** it SHALL use React with TypeScript on Vite, Tailwind CSS with
  shadcn/ui primitives (Radix underneath, for accessible components), TanStack
  Query for server state, TanStack Table for tabular results, ECharts for charts,
  and Motion for animation
- **AND** TypeScript SHALL run in strict mode, matching `mypy --strict` on the
  Python side

#### Scenario: Types come from the API
- **WHEN** the frontend describes a request or response
- **THEN** the types SHALL be generated from the OpenAPI schema, not hand-written
- **AND** a stale generated client SHALL fail the build, so an API change cannot
  silently break the UI

#### Scenario: No Node needed to install the tool
- **WHEN** a user runs `pip install quantfolio-cli[web]`
- **THEN** pre-built static assets SHALL be included in the wheel
- **AND** `qf serve` SHALL work with no Node toolchain present

### Requirement: Every CLI capability has a view

#### Scenario: Full coverage
- **WHEN** the UI is built
- **THEN** every command in the registry SHALL have a view that can invoke it
- **AND** the parity test from `http-api` SHALL fail the build if one does not

#### Scenario: Forms are generated from the registry
- **WHEN** a command's view renders
- **THEN** its inputs SHALL be generated from the registry's parameter
  declarations, including types, defaults, and help text as field hints

#### Scenario: Defaults are visible, not hidden
- **WHEN** a form renders a parameter with a default
- **THEN** the default SHALL be shown as the pre-filled value
- **AND** defaults that change the meaning of a result — shrinkage, transaction
  costs, the withdrawal rate — SHALL be visible without opening an advanced panel

#### Scenario: The equivalent command is always shown
- **WHEN** a form is filled in
- **THEN** the equivalent `qf` command line SHALL be displayed and copyable
- **AND** it SHALL update live as fields change, so the UI teaches the CLI rather
  than replacing it

### Requirement: Dark mode

#### Scenario: Dark by default
- **WHEN** the app first loads with no stored preference
- **THEN** it SHALL render in dark mode

#### Scenario: Both themes are complete
- **WHEN** either theme is active
- **THEN** every surface, including charts, SHALL use that theme's tokens
- **AND** no element SHALL be unreadable or retain a hard-coded colour from the
  other theme

#### Scenario: Preference persists
- **WHEN** a user switches theme
- **THEN** the choice SHALL persist across reloads
- **AND** a "system" option SHALL follow the OS setting

#### Scenario: Contrast
- **WHEN** any text or meaningful UI element is rendered in either theme
- **THEN** it SHALL meet WCAG 2.1 AA contrast

### Requirement: Result visualization

#### Scenario: Interactive efficient frontier
- **WHEN** a frontier result is displayed
- **THEN** it SHALL render as a risk/return scatter with the curve, the
  minimum-variance and maximum-Sharpe points marked
- **AND** hovering or dragging a point SHALL show that portfolio's weights

#### Scenario: Backtest visualization
- **WHEN** a backtest completes
- **THEN** the equity curve, the drawdown series, and the weight history over time
  SHALL be charted, with the benchmark overlaid on the equity curve

#### Scenario: Charts state their assumptions
- **WHEN** a chart displays a computed result
- **THEN** the estimators, data window, and costs used SHALL be visible on or
  beside it, matching the provenance the CLI prints in its header

#### Scenario: Every chart's data is obtainable
- **WHEN** any chart is displayed
- **THEN** the underlying rows SHALL be downloadable as CSV and viewable as a table
- **AND** a picture SHALL never be the only representation of a number

#### Scenario: In-sample results are labelled as such
- **WHEN** an optimization result computed in-sample is displayed
- **THEN** it SHALL be visually distinguished from walk-forward results
- **AND** the UI SHALL link to the backtest for the same inputs, carrying 0002's
  honesty rule into the visual surface

### Requirement: Animation

#### Scenario: Animation serves comprehension
- **WHEN** a result appears
- **THEN** transitions SHALL clarify what changed — a frontier drawing along its
  curve, a chart morphing between parameter sets — rather than decorate

#### Scenario: Reduced motion is respected
- **WHEN** the browser reports `prefers-reduced-motion: reduce`
- **THEN** animations SHALL be replaced by instant state changes
- **AND** no information SHALL be conveyed only by motion

#### Scenario: Animation never gates interaction
- **WHEN** an animation is playing
- **THEN** the interface SHALL remain interactive, and any animation SHALL be
  interruptible

#### Scenario: Progress is real
- **WHEN** a job's progress is shown
- **THEN** it SHALL reflect actual reported progress from the job stream
- **AND** SHALL NOT animate a fake indeterminate bar toward a number it does not know

### Requirement: Long-running work in the interface

#### Scenario: Immediate feedback
- **WHEN** a user submits work
- **THEN** the UI SHALL show the job as queued within 200 ms

#### Scenario: Navigation does not cancel work
- **WHEN** a user navigates away from a running job and returns
- **THEN** the job SHALL still be running or complete, and its state SHALL be shown

#### Scenario: Cancellable
- **WHEN** a job is running
- **THEN** the UI SHALL offer to cancel it

### Requirement: History and saved state

#### Scenario: Run history is browsable
- **WHEN** the history view opens
- **THEN** runs persisted by 0003 SHALL be listed newest first with their command,
  parameters, and summary result

#### Scenario: Re-run and compare
- **WHEN** a past run is opened
- **THEN** its form SHALL be re-populated with the stored parameters
- **AND** two runs of the same command SHALL be comparable side by side

#### Scenario: Portfolios are managed in the UI
- **WHEN** the portfolio view opens
- **THEN** portfolios saved by 0003 SHALL be creatable, editable, and deletable
- **AND** changes SHALL be visible to the CLI immediately, because both read one
  database

### Requirement: Accessibility and responsiveness

#### Scenario: Keyboard operable
- **WHEN** a user navigates with a keyboard alone
- **THEN** every control SHALL be reachable and operable, with a visible focus
  indicator

#### Scenario: Screen readers
- **WHEN** a chart is rendered
- **THEN** an accessible text or table alternative SHALL be available

#### Scenario: Small screens
- **WHEN** the viewport is 400 px wide
- **THEN** the layout SHALL remain usable with no horizontal page scroll
- **AND** wide tables SHALL scroll within their own container

### Requirement: Performance budget

#### Scenario: Bundle size is a CI gate
- **WHEN** the frontend is built
- **THEN** the initial JavaScript bundle SHALL be under 300 KB compressed
- **AND** exceeding it SHALL fail the build, not warn

#### Scenario: Charts load on demand
- **WHEN** the app first loads
- **THEN** charting and animation libraries SHALL be code-split and loaded only
  when a view needs them

#### Scenario: Interaction latency
- **WHEN** a user interacts with a rendered chart
- **THEN** it SHALL respond within 100 ms for a result of up to 10,000 points

### Requirement: Not investment advice

#### Scenario: The disclaimer carries over
- **WHEN** any analysis result is displayed
- **THEN** the not-investment-advice disclaimer SHALL be present and legible
- **AND** it SHALL NOT be dismissible in a way that persists across sessions
