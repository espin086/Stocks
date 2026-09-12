# Why your backtest looks too good

`sobres optimize markowitz` prints a Sharpe ratio. `sobres optimize backtest`
prints a smaller one for the same tickers and the same objective. The gap
between them is the most useful number this tool produces, and this page is
about why it exists and how to read it.

## The in-sample number is an error maximizer

Mean-variance optimization takes two inputs it cannot observe — expected
returns and their covariance — and estimates both from the past. Estimation
error in expected returns is large: a decade of daily data pins a stock's
annual mean down to roughly ±10 percentage points. The optimizer does not know
that. It treats every estimate as truth, leans hardest on the assets whose
means were overestimated by luck, and reports a Sharpe ratio computed on the
very data that produced the estimates.

That number is not a forecast. It is the best any portfolio could have done on
that history, chosen with full knowledge of it. Michaud (1989) called
mean-variance "error maximization" for this reason, and it is why `markowitz`
output carries an `in-sample` line.

## What the backtest does differently

`backtest` never lets the optimizer see the future:

1. At each rebalance date `t`, only returns strictly before `t` (the
   `--lookback` window) are handed to the estimators and the solver.
2. The resulting weights are held — drifting with realized returns — until
   the next rebalance.
3. Every rebalance pays `--cost-bps` on turnover. The default is 10 bps, not
   0, because a costless backtest flatters every strategy that trades.
4. An equal-weight portfolio, rebalanced on the same dates with the same
   costs, runs alongside as the benchmark.

The test suite asserts the first point mechanically: perturbing every
observation at or after `t` by a large factor leaves the weights at `t`
bit-identical.

## How to read the gap

| You see | It usually means |
|---|---|
| In-sample Sharpe far above walk-forward Sharpe | Estimation error dominated; the "optimal" weights were fitted noise |
| Walk-forward below the equal-weight benchmark | The optimizer's extra information was worth less than the turnover it cost |
| High turnover, most of the return lost to costs | The estimates change a lot between rebalances; a longer lookback or shrinkage helps |
| Walk-forward close to in-sample | The universe is well-behaved (few, diversified assets) or the window is short |

## What sobres does about it by default

- **Shrinkage.** Ledoit-Wolf shrinkage is the default covariance estimator,
  not an option to discover. The shrinkage intensity is printed.
- **The frontier, not the point.** `sobres optimize frontier` shows the whole
  trade-off; a curve invites less false precision than a single optimum.
- **Costs on.** 10 bps per side unless you say otherwise.
- **Survivorship stated.** A ticker list chosen today reflects survivors.
  Every result says so, because no free source provides point-in-time
  constituents and the tool will not pretend to correct for it.
- **Concentration warned.** An unconstrained max-Sharpe solution that puts more
  than half the portfolio in one asset says so and suggests `--max-weight`.

## References

- Markowitz, H. (1952). Portfolio Selection. *Journal of Finance* 7(1).
- Michaud, R. (1989). The Markowitz Optimization Enigma: Is 'Optimized'
  Optimal? *Financial Analysts Journal* 45(1).
- Ledoit, O. & Wolf, M. (2004). A well-conditioned estimator for
  large-dimensional covariance matrices. *Journal of Multivariate Analysis* 88.
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal Versus Naive
  Diversification: How Inefficient is the 1/N Portfolio Strategy? *Review of
  Financial Studies* 22(5). — the paper behind the equal-weight benchmark.

*For research and education only. Not investment advice.*
