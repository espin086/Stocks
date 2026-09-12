# landing-page — spec delta (0006)

## ADDED Requirements

### Requirement: Stack and hosting

#### Scenario: Chosen libraries
- **WHEN** the site is built
- **THEN** it SHALL use Vite with TypeScript in strict mode, Tailwind CSS for
  styling, GSAP with ScrollTrigger for scroll-driven animation, Lenis for smooth
  scrolling, and ECharts for the charted figures
- **AND** it SHALL be a static build with no server-side component

#### Scenario: Published automatically
- **WHEN** a commit lands on `main` that changes `site/`
- **THEN** GitHub Actions SHALL build and deploy it to GitHub Pages
- **AND** the deploy job SHALL hold `pages: write` and `id-token: write` while the
  workflow default remains `contents: read`, per 0000's least-privilege rule

#### Scenario: Broken builds do not deploy
- **WHEN** the site build or its checks fail
- **THEN** nothing SHALL be deployed and the previous version SHALL remain live

#### Scenario: Shares the app's design tokens
- **WHEN** colours, type scale, or spacing are defined
- **THEN** they SHALL come from tokens shared with the 0004 frontend, so the page
  and the product are visibly one thing

### Requirement: Dark theme

#### Scenario: Dark by design
- **WHEN** the page loads
- **THEN** it SHALL render dark, regardless of the visitor's system preference
- **AND** there SHALL be no light variant to maintain

#### Scenario: Contrast
- **WHEN** any text or meaningful element renders
- **THEN** it SHALL meet WCAG 2.1 AA contrast against its background

#### Scenario: No flash
- **WHEN** the page first paints
- **THEN** it SHALL paint on its dark background, with no light flash

### Requirement: Animation

#### Scenario: Animation shows the product
- **WHEN** an animated figure plays
- **THEN** it SHALL depict the tool's own output — a frontier drawing along its
  curve, an equity curve advancing, a terminal returning real results

#### Scenario: The hero frontier
- **WHEN** the hero enters the viewport
- **THEN** an efficient frontier SHALL draw along its path and the maximum-Sharpe
  point SHALL be marked and labelled
- **AND** the plotted data SHALL be a real computed frontier checked into `site/`,
  not hand-drawn coordinates

#### Scenario: The terminal transcript is real
- **WHEN** the terminal figure types a command and returns output
- **THEN** that output SHALL be a recorded transcript of that command actually
  running, stored in `site/` and regenerable by a script
- **AND** it SHALL NOT be written by hand to look plausible

#### Scenario: Reduced motion
- **WHEN** the browser reports `prefers-reduced-motion: reduce`
- **THEN** every animated element SHALL render immediately in its final state
- **AND** smooth scrolling SHALL be disabled, leaving native scrolling

#### Scenario: No information only in motion
- **WHEN** an animation conveys a fact
- **THEN** that fact SHALL also be present as text

#### Scenario: Animation never blocks reading
- **WHEN** the page is scrolled quickly
- **THEN** content SHALL be readable in its final state without waiting for an
  animation to complete
- **AND** no section SHALL trap scrolling

### Requirement: Content accuracy

#### Scenario: Only shipped capabilities are claimed
- **WHEN** the page describes what the tool does
- **THEN** every claim SHALL correspond to a capability in the released version
- **AND** planned work SHALL appear only under an explicit roadmap heading, marked
  as not yet available

#### Scenario: Install commands are generated
- **WHEN** the page is built
- **THEN** the install commands and the version shown SHALL be generated from the
  repository at build time
- **AND** the build SHALL fail if the version cannot be resolved, so the page
  cannot go stale silently

#### Scenario: Numbers are sourced
- **WHEN** a figure shows a performance or backtest number
- **THEN** the tickers, date range, and parameters that produced it SHALL be stated
  beside it

#### Scenario: Disclaimer
- **WHEN** the page renders
- **THEN** it SHALL carry the not-investment-advice disclaimer
- **AND** any backtested figure SHALL be labelled as hypothetical

### Requirement: Performance

#### Scenario: Lighthouse budget
- **WHEN** the built site is audited on a simulated mid-range mobile device
- **THEN** Performance, Accessibility, and Best Practices SHALL each be at least 95
- **AND** falling below SHALL fail the build

#### Scenario: Bundle budget
- **WHEN** the site is built
- **THEN** the initial JavaScript bundle SHALL be under 150 KB compressed
- **AND** exceeding it SHALL fail the build

#### Scenario: Readable before JavaScript
- **WHEN** the page loads with JavaScript disabled or still loading
- **THEN** the headline, description, install commands, and repository link SHALL
  be present and readable in the served HTML

#### Scenario: Deferred libraries
- **WHEN** the page first paints
- **THEN** animation and charting libraries SHALL NOT block that paint

#### Scenario: Self-hosted assets
- **WHEN** the page loads fonts, scripts, or styles
- **THEN** they SHALL be served from the same origin
- **AND** no third-party request SHALL be made at runtime

### Requirement: Privacy

#### Scenario: No tracking
- **WHEN** the page is loaded
- **THEN** it SHALL set no cookies, use no analytics, and make no third-party
  request
- **AND** consequently SHALL require no consent banner

### Requirement: Accessibility and reach

#### Scenario: Keyboard
- **WHEN** the page is navigated by keyboard alone
- **THEN** every link and control SHALL be reachable with a visible focus indicator
- **AND** copy buttons SHALL be operable and announce their result

#### Scenario: Structure
- **WHEN** the page is read by a screen reader
- **THEN** headings SHALL form a correct hierarchy, figures SHALL have text
  alternatives, and decorative animation SHALL be hidden from the accessibility tree

#### Scenario: Small screens
- **WHEN** the viewport is 400 px wide
- **THEN** the page SHALL be fully readable with no horizontal scroll
- **AND** every animated figure SHALL remain legible or degrade to a static one

#### Scenario: Link previews
- **WHEN** the page URL is shared
- **THEN** Open Graph and Twitter card metadata SHALL render a title, description,
  and image
- **AND** the image SHALL depict the actual product
