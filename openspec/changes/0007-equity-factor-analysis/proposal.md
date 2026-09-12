---
change: 0007-equity-factor-analysis
milestone: v1.3
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization]
status: proposed
planning_depth: proposal + spec delta (design and tasks written when 0006 lands)
---

# 0007 — Equity and factor analysis

## Outcome

```bash
sobres analyze stock NVDA
sobres analyze factors NVDA --model ff5 --start 2015-01-01
sobres analyze factors --tickers AAPL MSFT NVDA --model ff5+mom --format csv
```

A single-stock dashboard, and a Fama-French regression that answers the question the
whole thing exists for: **is this stock's excess return explained by known risk
factors, or is there alpha?** — with the t-statistic that says whether to believe it.

## Why

Factor analysis is the part of this tool that is genuinely hard to get elsewhere in
a usable form. The data (Ken French) lands in 0001, the returns and risk machinery
lands in 0002, so by this point the change is mostly regression plumbing and careful
statistics reporting.

It also feeds forward: factor exposures become a candidate expected-return estimator
for the optimizer, and factor-tilted portfolio construction becomes possible.

## What changes

- **New capability `equity-analysis`**: `core/factors.py` (CAPM, FF3, FF5,
  FF5+momentum, rolling betas) and a fundamentals summary built on yfinance.
- **New CLI group `sobres analyze`**: `stock`, `factors`.
- `statsmodels` moves from the `econ` extra into the base install, or the regression
  is implemented on `numpy` directly — decided in design, based on whether the OLS
  diagnostics needed (HAC standard errors) justify the dependency.

## Non-goals

- No DCF or intrinsic-value modeling. Its assumptions dominate its output; it would
  be false precision wearing a spreadsheet.
- No analyst estimates, earnings-call transcripts, or sentiment. Different data
  problem entirely.
- No point-in-time fundamentals. yfinance serves current values, so any
  fundamentals-based backtest would be survivorship- and restatement-biased. The
  spec states this limitation in the output rather than hiding it.
- No custom or proprietary factor construction. Ken French's published factors only.

## Risks

| Risk | Mitigation |
|---|---|
| Users read a positive alpha as a stock pick | Always report the t-statistic and p-value next to alpha; the spec requires stating explicitly when alpha is not statistically distinguishable from zero |
| Overlapping/autocorrelated residuals inflate significance | Newey-West (HAC) standard errors alongside OLS; report both |
| Short samples produce unstable betas | Enforce a minimum observation count; offer rolling-window betas so instability is visible rather than averaged away |
| Frequency mismatch (daily prices vs monthly factors) | Alignment is explicit via 0001's `align_frames`; monthly is the default for factor work, matching how the factors are published |
