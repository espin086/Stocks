# 0010 — Design

## The identity, kept exact

`core/fx.py::decompose_return` returns local, fx, cross and total per period
with `total = local + fx + local·fx` holding exactly; the compounded window
keeps the identity by defining the compounded cross term as the residual.
The cross term is always its own column. `currency_risk` reports volatility
in base currency, volatility with currencies held fixed (the same weights on
local returns), their difference, the per-asset correlation of local return
with its currency return, and exposure by currency — so the currency's
contribution is visibly a function of correlation, never presented as additive.

## Hedging under covered interest parity

A hedged return is `r_local + (i_base − i_foreign) / periods`, the forward
premium of a rolling short-dated forward. Short rates come from FRED 3-month
series per currency (`SHORT_RATE_SERIES` in `cli/commands/fx.py`); a missing
leg raises `InsufficientDataError` naming the currency and series, and no
unhedged result is substituted. Every hedged figure — `fx hedge` and the
optimizer's `--hedged` — carries the caveat that this excludes transaction
costs, bid-ask and basis and is not an achievable realized return.

## PPP: absolute and relative never meet

`core/ppp.py` keeps `PppFigure` (an absolute conversion factor with its
`Vintage`) apart from `relative_ppp` (a drift from an anchor). `ppp_rate`
refuses non-absolute inputs and `combine_guard` refuses to mix the two. Every
PPP output starts with the framing that PPP is a long-run relationship with
little short-run predictive power, reports a gap rather than a target, names
which currency is over- or undervalued in words, and notes that sustained
deviations are normal. No command projects a rate; the test suite greps the
group's names and help for forecasting words.

## Sources, through the port

`PppProvider` is a protocol; `WorldBankPppProvider` (ICP `PA.NUS.PPP`,
keyless) is the default and `OecdPppProvider` the alternative, selected by
`SOBRES_PPP_PROVIDER`. Both cache annual factors through the observation
store and carry the vintage (benchmark year, reference period, release date)
in `series_meta`, so it survives a cache hit. A benchmark older than
`SOBRES_PPP_STALE_YEARS` (default 3) is flagged with its age. Real effective
exchange rates are the BIS published broad CPI-based series; the tool builds
no trade weights. Country codes are ISO 3166-1 alpha-3 from a fixed table;
alpha-2 or names are errors, never near matches.

## Goals across borders

`sobres plan … --save-goal NAME` stores the target and its funding inputs;
`sobres ppp adjust-goal --goal NAME --to PRT` (or `--target`) restates the
target at the destination's price level, shows the market-rate figure beside
it, recomputes months and date to goal, and states the basket, not-modeled
and exchange-rate-risk caveats.

## Rejected

| Choice | Rejected | Why |
|---|---|---|
| CIP forward premium from FRED short rates | Forward quotes | No keyless forward data; CIP holds closely at these tenors and the caveat is stated |
| Fixed ISO3 table | `pycountry` | A dependency for a lookup that must fail loudly on near matches anyway |
| Vintage in `series_meta` | A second PPP table | One store, no sidecars (0003) |
| Grep-based "no forecasting surface" test | Review | The rule is code, per the project's test discipline |
