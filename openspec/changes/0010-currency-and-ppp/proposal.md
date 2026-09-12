---
change: 0010-currency-and-ppp
milestone: v1.6
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization, 0008-goal-planning]
status: implemented
planning_depth: proposal + spec deltas + design + tasks
---

# 0010 — Exchange rates and purchasing power parity

## Outcome

```bash
sobres fx rates EURUSD USDJPY --start 2015-01-01
sobres fx convert 100000 --from USD --to EUR --on 2026-09-01

# How much of my international return was the company, and how much was the dollar?
sobres fx attribution --tickers NESN.SW 7203.T ASML.AS --base USD --start 2015-01-01

# What would hedging have cost, and would it have helped?
sobres fx hedge --tickers ... --base USD --compare unhedged

# Is the dollar expensive against the euro right now, by PPP?
sobres ppp compare --base USD --vs EUR GBP MXN PTE

# My FIRE number is $2.1M for a US lifestyle. What is it in Portugal?
sobres ppp adjust-goal --goal fire --to PRT
```

Two related things: **exchange rates**, which change what an international
portfolio actually returned, and **purchasing power parity**, which changes what a
retirement number actually buys.

## Why

**For the portfolio.** A US investor holding Nestlé earned the stock's return *and*
the franc's move against the dollar, multiplied together. A tool that reports the
local-currency return is reporting a number nobody received. 0001 makes conversion
correct; this change makes the currency component *visible* — how much of the
return was the business and how much was the exchange rate, and what hedging would
have cost.

**For the plan.** This is the more useful half. `sobres plan retire` produces a number
for a lifestyle in one country. The question people actually have is whether that
number goes further somewhere else, and PPP is the right tool for exactly that
question — comparing what a currency *buys* rather than what it *trades for*.
Market rates and price levels diverge persistently, and the gap is the entire
point: a dollar that buys 40% more in Portugal than the market rate suggests
changes a FIRE date by years.

It comes last because it is the only milestone that makes every earlier one
international, and doing that before the domestic case is trustworthy would be
building breadth on an unproven base.

## What changes

- **New capability `fx-analytics`** — `core/fx.py`: currency return decomposition,
  hedged-return construction from interest-rate differentials, currency
  contribution to portfolio risk, and correlation of FX to the underlying assets.
- **New capability `purchasing-power`** — `core/ppp.py`: absolute and relative PPP,
  real exchange rates, over/undervaluation against market rates, and PPP-adjusted
  restatement of any goal from 0008.
- **New CLI groups** `sobres fx` and `sobres ppp`.
- New `PppProvider` behind a protocol: World Bank ICP (`PA.NUS.PPP`, keyless) as
  the default, OECD PPP and comparative price levels as an alternative, and BIS
  published real effective exchange rates.
- `--base <currency>` accepted by the analytical commands, and `--hedged` by the
  portfolio commands.

## Non-goals

- **No FX forecasting.** Exchange rates are close to a random walk at the horizons
  this tool works on, and PPP has essentially no short-run predictive power. A
  `sobres fx forecast` would be the single most misleading thing in the codebase.
  PPP is reported as a *valuation gap*, never as a signal.
- **No currency trading, carry strategies, or FX-timing backtests.** Reporting
  what the currency did is in scope; recommending a currency position is not.
- No forward, futures, or options pricing. Hedged returns are constructed from
  interest-rate differentials under covered interest parity, which is what the
  data supports; it is not a derivatives pricing library.
- No intraday or tick FX.
- **No Big Mac index.** A single-good index is a teaching device, not a basis for
  restating someone's retirement number, and its data carries its own licensing.
- No cost-of-living estimates from crowd-sourced sites. PPP comes from national
  statistical offices via the World Bank and OECD, or it is not reported.
- No tax, residency, visa, or healthcare modeling. PPP says what money buys, not
  whether moving is a good idea, and the output says so.

## Risks

| Risk | Mitigation |
|---|---|
| **PPP read as an FX forecast** — the classic misuse | Every PPP output states that PPP is a long-run relationship with no short-run predictive power, and reports a *gap* rather than a target or a direction; no command produces a projected rate |
| Rate direction inverted somewhere | 0001 settles this by type: `CurrencyPair(base, quote)`, and call sites never touch a raw rate; round-trip conversion is a test |
| Return conversion approximated as `r_local + r_fx` | 0001 requires the exact `(1+r_local)(1+r_fx)-1` identity, asserted against price-level conversion |
| PPP series are revised, benchmark-year dependent, and published with long lags | The benchmark year, vintage, and release date are reported with every PPP figure; a figure older than a threshold is flagged |
| A national CPI basket does not match one household's spending | Output states that PPP reflects a national basket; goal restatement is presented as a scale factor with its basis named, not as a personalized budget |
| Hedged returns presented as achievable | Hedged figures are labelled as an interest-rate-differential approximation excluding transaction costs and basis, with the assumption stated in the output |
| International data thins out for smaller markets | Coverage gaps raise `InsufficientDataError` naming the country and series rather than silently shortening a window |
