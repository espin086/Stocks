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

### Requirement: Settings and health in the UI

#### Scenario: Settings page is generated
- **WHEN** the settings view renders
- **THEN** every setting declared in 0001's settings registry SHALL appear as a
  field, with its description and how-to-obtain link, secrets masked and never
  echoed back
- **AND** saving SHALL write through the same code path as `qf config set`

#### Scenario: Live validation in the browser
- **WHEN** a setting with a live validator is saved
- **THEN** the UI SHALL offer to verify it and show the result, mirroring
  `qf init`

#### Scenario: Doctor has a view
- **WHEN** the health view renders
- **THEN** it SHALL show `qf doctor`'s checks with the same statuses, messages,
  and next steps, from the same check registry
- **AND** a check with a registered fix SHALL offer to run it, never touching a
  secret

#### Scenario: `qf init --web`
- **WHEN** `qf init --web` runs once this change has landed
- **THEN** it SHALL behave as `qf open settings`, the browser form of the same
  wizard

### Requirement: Launching the UI from the CLI

The browser is one command away from the terminal, and never the only way in.

#### Scenario: `qf open`
- **WHEN** `qf open` runs and no server is listening on the configured port
- **THEN** it SHALL start the server bound to loopback, wait for the health
  endpoint to pass, open the default browser to the app, and keep serving until
  interrupted
- **AND** the URL SHALL be printed to stderr before the browser is launched, so
  it is available even if the launch fails

#### Scenario: Server already running
- **WHEN** `qf open` runs and a quantfolio server already answers on the port
- **THEN** it SHALL open the browser to that server and exit 0 without starting
  a second one
- **AND** a non-quantfolio process on the port SHALL produce an error naming the
  port and suggesting `--port`

#### Scenario: Targets
- **WHEN** `qf open <target>` runs
- **THEN** `target` SHALL accept `settings`, `doctor`, `runs`, `run <id>`,
  `portfolio <name>`, and any registry command name, opening that view directly
- **AND** the accepted set SHALL be derived from the frontend view manifest, so
  a view that exists is always reachable and one that does not is rejected with
  the list of those that are

#### Scenario: Headless is not an error
- **WHEN** no browser can be launched — no display, an SSH session, or inside
  the container
- **THEN** `qf open` SHALL print the URL and exit 0
- **AND** `--print-url` SHALL force that behavior anywhere

#### Scenario: Browser choice is respected
- **WHEN** the `BROWSER` environment variable is set
- **THEN** it SHALL be honored, via the platform's standard launcher

#### Scenario: Never a token in the URL
- **WHEN** the server requires a token
- **THEN** `qf open` SHALL open the app's entry page and the user SHALL paste the
  token once there, per `http-api`; the token SHALL NOT be placed in the URL

#### Scenario: `qf serve --open`
- **WHEN** `qf serve --open` runs
- **THEN** it SHALL behave as `qf serve` followed by the browser launch above,
  once healthy

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
