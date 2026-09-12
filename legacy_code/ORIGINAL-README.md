# Stocks

A small set of scripts for deciding where money should go. Two R scripts solve allocation
problems with linear programming: one splits a fixed budget across investment vehicles to
maximize average return under risk and category constraints, the other spreads money across
personal financial choices (extra student-loan payments, 401k, paying off a home, buying a
home, buying stocks, saving cash) to maximize total net present value subject to how much cash
is available each year. Two Python files pull daily price history from Yahoo Finance. A
`legacy_code/` folder holds an older R pipeline that downloaded S&P 500 prices and Federal
Reserve macro series, cleaned and merged them, and trained models with `caret`.

The R optimization scripts and the Python data puller are not wired together. They are separate
pieces in one repo, not one pipeline.

## Features

- Portfolio allocation by linear program: maximize return per dollar with a budget equality, an
  average-risk ceiling, a category minimum, and a cross-category ratio constraint.
- Multi-year personal finance allocation by linear program: maximize NPV of six competing uses
  of money against a per-year cash constraint read from a CSV.
- `StockMarketData`, a thin wrapper over `yfinance` that downloads OHLC history for one ticker
  and exposes open, close, high, and low as pandas Series. Runnable as a CLI.
- `npv.data.csv`, 49 periods of payment and return cash flows used by the NPV script.

## Requirements

There is no `requirements.txt` or `DESCRIPTION` file in the repo. The imports in the code call for:

**Python 3**
- `yfinance`
- `pandas`
- `numpy`
- `torch` (imported by `StockHunter.py` but not used yet)
- `scikit-learn` (`MinMaxScaler` imported by `StockHunter.py` but not used yet)

**R**
- `linprog` (both optimization scripts)
- `RCurl`, `foreign` (Financial Portfolio Optimization)
- `FinCal` (Investing Over Time, for `npv()`)

The `legacy_code/` scripts additionally use `quantmod`, `zoo`, `tseries`, `caret`, `reshape`,
`DataCombine`, `lubridate`, `doParallel`, and `Rlinkedin`.

## Installation

```bash
git clone https://github.com/espin086/Stocks.git
cd Stocks
pip install yfinance pandas numpy torch scikit-learn
```

For the R side, from an R session:

```r
install.packages(c("linprog", "RCurl", "foreign", "FinCal"))
```

## Usage

Download price history for one ticker. The CLI takes three positional arguments and prints open,
close, high, and low:

```bash
python StockMarketData.py AAPL 2022-01-01 2022-02-01
```

Or from Python:

```python
from StockMarketData import StockMarketData

data = StockMarketData('AAPL')
data.get_data('2022-01-01', '2022-02-01')
print(data.get_close_price())
```

`StockHunter.py` takes no arguments. Run it and it pulls five years of AAPL history ending today
and prints the close series:

```bash
python StockHunter.py
```

Run the budget allocation LP. It fetches the investment table (return and risk per vehicle) from
a published Google Sheet over HTTP, so it needs network access:

```bash
Rscript "Financial Portfolio Optimization.R"
```

Run the NPV allocation LP. It reads `npv.data.csv`. Note that the script calls
`setwd("~/Desktop")` before reading, so either move the CSV to your Desktop or edit that line to
point at the repo:

```bash
Rscript "Investing Over Time.R"
```

There are no environment variables or API keys anywhere in the code. Yahoo Finance and the
Google Sheet are both fetched unauthenticated.

## Project structure

```
Financial Portfolio Optimization.R   Budget-allocation LP; pulls returns and risk from a Google Sheet
Investing Over Time.R                NPV-maximizing LP across six personal financial choices
StockMarketData.py                   yfinance wrapper class plus an argparse CLI
StockHunter.py                       Script that pulls 5 years of AAPL closes; ML imports unused
npv.data.csv                         49 periods of cash flows and per-year cash constraints
legacy_code/                         Older R pipeline, hardcoded Windows paths, not runnable as-is
  Import - All Stock Prices.R        Downloads S&P 500 constituent prices via tseries
  Import - Fed Macro Data.R          Pulls FRED series (rates, oil, FX) via quantmod
  Import - Company Financials.R      Pulls balance sheet, income, cash flow via quantmod
  Import - Linkedin CEO Data.R       LinkedIn connection pull via Rlinkedin
  Clean - All Stock Prices.R         Reshapes wide price data to tidy date/ticker/price
  Clean - Fed Macro Data.R           Builds log-return lags of each Fed series
  Merge.R                            Joins prices and macro data, splits train/test/validation
  Analysis - Merged.R                Trains models per ticker with caret and doParallel
  Initial Analysis - 01-23-15.R      First-pass filtering of a stock universe file
  *.rattle                           Saved Rattle GUI project files
  README.md                          Unfilled Code for San Francisco template
```

## How it works

Both R scripts are linear programs solved with `linprog::solveLP`.

**Financial Portfolio Optimization.R** treats the fraction of the budget going to each of six
vehicles as the decision variables. The objective is the vector of returns (column 2 of the
sheet, divided by 100), maximized. Four constraints:

1. Budget: the fractions sum to exactly 1.
2. Average risk: `risk - 5` dotted with the allocation must be at most 0, which enforces a
   weighted average risk score of 5 or less.
3. Commercial loans: at least 20% of the total goes to the fourth vehicle.
4. Mortgages: second mortgages and personal loans, weighted 2 and 3, must not exceed first
   mortgages. The comment describes a plain sum; the coefficients `c(-1, 2, 3, 0, 0, 0)` weight
   the two terms rather than summing them, so the code and the comment disagree.

**Investing Over Time.R** computes, at a 5% discount rate, the NPV of the net cash-flow column
for each of the six options in `npv.data.csv`, then maximizes total NPV. The constraint matrix
is the per-option payment columns with signs flipped, and the right-hand side is the
`financial.constraints` column, so in each period the money committed cannot exceed the money
available. The script prints `answer$opt`, `answer$solution`, and `answer$con`. The header
comments say the assumptions were not validated and recommend checking the NPV math with a
wealth advisor.

The Python side does no optimization. `StockMarketData` calls `yfinance.download` and returns
columns off the resulting DataFrame. `StockHunter.py` imports torch and `MinMaxScaler` but never
uses them, so the price-prediction work those imports point at has not been written yet.

## License

No LICENSE file in the repo.
