#!/usr/bin/env python3
"""Generate provider fixtures in each vendor's exact payload shape, deterministically.

The recording environment for 0001 had no route to Yahoo, FRED, the ECB or the
Ken French Data Library, so these fixtures were *synthesized* rather than
recorded: every file has the columns, separators, preambles and quirks of the
real payload (yfinance's ``Adj Close``/``Close`` split, FRED's ``"."`` for a
missing value, the ECB's SDMX csvdata header, Ken French's multi-table CSV with
its free-text preamble and annual table) so the real parsers are exercised, but
the numbers are a seeded random walk. ``tests/fixtures/README.md`` says so, and
``scripts/record_fixtures.py`` replaces them with live recordings when run with
network access — a reviewable diff in its own commit.

A handful of published values are kept verbatim where a test asserts a known
number: the first Fama-French monthly row (July 1926: Mkt-RF 2.96, SMB -2.56,
HML -2.43, RF 0.22) from the Data Library.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
START, END = date(2015, 1, 2), date(2024, 12, 31)
SEED = 20260912

TICKERS = {
    # ticker: (start price, annual drift, annual vol, currency, dividend yield)
    "AAPL": (27.0, 0.22, 0.28, "USD", 0.008),
    "MSFT": (46.0, 0.20, 0.25, "USD", 0.010),
    "NVDA": (0.50, 0.40, 0.45, "USD", 0.001),
    "JNJ": (100.0, 0.06, 0.16, "USD", 0.028),
    "XOM": (90.0, 0.03, 0.24, "USD", 0.040),
    "GLD": (115.0, 0.05, 0.14, "USD", 0.0),
    "VOD.L": (22000.0, -0.02, 0.22, "GBp", 0.060),  # quoted in pence
}
SPLITS = {"AAPL": (date(2020, 8, 31), 4), "NVDA": (date(2021, 7, 20), 4)}
FX = {"USD": 1.16, "GBP": 0.78, "JPY": 140.0, "CHF": 1.06}


def business_days(start: date, end: date) -> pd.DatetimeIndex:
    days = pd.bdate_range(start, end)
    # US-style holidays: drop New Year's Day, July 4th, Christmas when on a weekday
    holidays = {(1, 1), (7, 4), (12, 25)}
    return pd.DatetimeIndex([d for d in days if (d.month, d.day) not in holidays])


def gbm(rng: np.random.Generator, n: int, s0: float, mu: float, sigma: float) -> np.ndarray:
    dt = 1 / 252
    steps = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rng.standard_normal(n)
    return s0 * np.exp(np.cumsum(np.insert(steps[:-1], 0, 0.0)))


def write_yfinance(rng: np.random.Generator) -> None:
    out = ROOT / "yfinance"
    out.mkdir(parents=True, exist_ok=True)
    index = business_days(START, END)
    meta: dict[str, dict[str, object]] = {}
    for ticker, (s0, mu, sigma, currency, dy) in TICKERS.items():
        n = len(index)
        adj = gbm(rng, n, s0, mu, sigma)
        # Quarterly cash dividends: the adjustment factor steps down going back.
        div_dates = [
            i
            for i, d in enumerate(index)
            if d.month in (3, 6, 9, 12) and d.day >= 15 and index[i - 1].day < 15
        ]
        cum = np.ones(n)
        for i in div_dates:
            cum[:i] *= 1 - dy / 4
        close = adj / cum  # unadjusted close is higher before each dividend
        if ticker in SPLITS:
            split_date, ratio = SPLITS[ticker]
            before = index < pd.Timestamp(split_date)
            close = np.where(before, close * ratio, close)
        noise = rng.uniform(0.995, 1.005, size=(n, 3))
        open_ = close * noise[:, 0]
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
        volume = rng.integers(5_000_000, 90_000_000, n)
        frame = pd.DataFrame(
            {
                "Open": open_,
                "High": high,
                "Low": low,
                "Close": close,
                "Adj Close": adj,
                "Volume": volume,
            },
            index=index,
        )
        frame.index.name = "Date"
        frame.round(6).to_csv(out / f"{ticker}.csv")
        meta[ticker] = {
            "currency": currency,
            "exchangeName": "LSE" if currency == "GBp" else "NMS",
            "symbol": ticker,
        }
    (out / "meta.json").write_text(
        json.dumps(
            {
                "recorded_at": None,
                "synthesized_at": datetime.now(UTC).isoformat(),
                "provider": "yfinance",
                "provider_version": "1.7.0 (shape)",
                "note": "synthesized in the shape of Ticker.history(auto_adjust=False); "
                "see tests/fixtures/README.md",
                "tickers": meta,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_fred(rng: np.random.Generator) -> None:
    out = ROOT / "fred"
    out.mkdir(parents=True, exist_ok=True)
    daily = pd.bdate_range(START, END)
    series = {
        "DGS10": (2.0, 0.03, daily),
        "DTB3": (0.05, 0.02, daily),
        "DEXUSEU": (1.16, 0.004, daily),
        "CPIAUCSL": (233.0, 0.3, pd.date_range(START, END, freq="MS")),
    }
    for name, (start, step, index) in series.items():
        n = len(index)
        walk = start + np.cumsum(rng.normal(0, step, n))
        if name == "CPIAUCSL":
            walk = start + np.cumsum(np.abs(rng.normal(0.4, step, n)))
        rows = []
        for d, v in zip(index, walk, strict=True):
            missing = name != "CPIAUCSL" and (d.month, d.day) in {(1, 1), (7, 4), (12, 25)}
            rows.append(
                {
                    "realtime_start": "2026-09-12",
                    "realtime_end": "2026-09-12",
                    "date": d.date().isoformat(),
                    "value": "." if missing else f"{max(v, 0.01):.2f}",
                }
            )
        payload = {
            "realtime_start": "2026-09-12",
            "realtime_end": "2026-09-12",
            "observation_start": START.isoformat(),
            "observation_end": END.isoformat(),
            "units": "lin",
            "output_type": 1,
            "file_type": "json",
            "order_by": "observation_date",
            "sort_order": "asc",
            "count": len(rows),
            "offset": 0,
            "limit": 100000,
            "observations": rows,
        }
        (out / f"{name}.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    (out / "meta.json").write_text(
        json.dumps(
            {
                "recorded_at": None,
                "synthesized_at": datetime.now(UTC).isoformat(),
                "provider": "fred",
                "api": "fred/series/observations file_type=json",
                "note": "synthesized in the API's response shape; see tests/fixtures/README.md",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_ecb(rng: np.random.Generator) -> None:
    out = ROOT / "ecb"
    out.mkdir(parents=True, exist_ok=True)
    index = pd.bdate_range(START, END)
    header = (
        "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,"
        "OBS_CONF,OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,BREAKS,COLLECTION,COMPILING_ORG,DISS_ORG,"
        "DOM_SER_IDS,PUBL_ECB,PUBL_MU,PUBL_PUBLIC,UNIT_INDEX_BASE,COMPILATION,COVERAGE,DECIMALS,"
        "NAT_TITLE,SOURCE_AGENCY,SOURCE_PUB,TITLE,TITLE_COMPL,UNIT,UNIT_MULT"
    )
    for ccy, level in FX.items():
        n = len(index)
        walk = level * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
        lines = [header]
        for d, v in zip(index, walk, strict=True):
            if (d.month, d.day) in {(1, 1), (12, 25), (12, 26), (5, 1)}:
                continue  # TARGET closing days: no quote published
            decimals = 2 if ccy == "JPY" else 4
            lines.append(
                f"EXR.D.{ccy}.EUR.SP00.A,D,{ccy},EUR,SP00,A,{d.date().isoformat()},{v:.{decimals}f},"
                f"A,F,,,P1D,,A,4F0,4F0,,,,,,,,{decimals},,4F0,,{ccy}/EUR,"
                f"ECB reference exchange rate,{ccy},0"
            )
        (out / f"{ccy}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "meta.json").write_text(
        json.dumps(
            {
                "recorded_at": None,
                "synthesized_at": datetime.now(UTC).isoformat(),
                "provider": "ecb",
                "api": "data-api.ecb.europa.eu EXR/D.<CCY>.EUR.SP00.A?format=csvdata",
                "note": "synthesized in the SDMX csvdata shape; see tests/fixtures/README.md",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _factor_rows(rng: np.random.Generator, dates: list[str], columns: list[str], scale: float):
    rows = []
    for d in dates:
        vals = rng.normal(0, scale, len(columns))
        if "RF" in columns:
            vals[columns.index("RF")] = abs(rng.normal(0.2 * scale, 0.05 * scale))
        rows.append(d + "".join(f",{v:8.2f}" for v in vals))
    return rows


def write_ken_french(rng: np.random.Generator) -> None:
    out = ROOT / "ken_french"
    out.mkdir(parents=True, exist_ok=True)
    months_ff3 = [p.strftime("%Y%m") for p in pd.period_range("1926-07", "2024-12", freq="M")]
    months_ff5 = [p.strftime("%Y%m") for p in pd.period_range("1963-07", "2024-12", freq="M")]
    days = [d.strftime("%Y%m%d") for d in pd.bdate_range(START, END)]
    years = [str(y) for y in range(1927, 2025)]

    def file(preamble: list[str], header: list[str], monthly: list[str], annual: list[str]) -> str:
        head = "," + ",".join(header)
        parts = [*preamble, "", head, *monthly, ""]
        parts += [" Annual Factors: January-December ", "", head, *annual, ""]
        return "\n".join(parts)

    def daily_file(preamble: list[str], header: list[str], rows: list[str]) -> str:
        return "\n".join([*preamble, "", "," + ",".join(header), *rows, ""])

    ff3 = ["Mkt-RF", "SMB", "HML", "RF"]
    ff5 = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    mom = ["Mom"]
    ff3_rows = _factor_rows(rng, months_ff3, ff3, 4.0)
    # Published July 1926 values, kept verbatim for the known-month regression test.
    ff3_rows[0] = "192607,    2.96,   -2.56,   -2.43,    0.22"
    (out / "F-F_Research_Data_Factors.CSV").write_text(
        file(
            [
                "This file was created by CMPT_ME_BEME_RETS using the 202412 CRSP database.",
                "The 1-month TBill return is from Ibbotson and Associates, Inc.",
            ],
            ff3,
            ff3_rows,
            _factor_rows(rng, years, ff3, 15.0),
        ),
        encoding="utf-8",
    )
    (out / "F-F_Research_Data_Factors_daily.CSV").write_text(
        daily_file(
            ["This file was created by CMPT_ME_BEME_RETS using the 202412 CRSP database."],
            ff3,
            _factor_rows(rng, days, ff3, 0.8),
        ),
        encoding="utf-8",
    )
    (out / "F-F_Research_Data_5_Factors_2x3.CSV").write_text(
        file(
            [
                "This file was created by CMPT_ME_BEME_OP_INV_RETS using the 202412 CRSP database.",
                "The 1-month TBill return is from Ibbotson and Associates, Inc.",
            ],
            ff5,
            _factor_rows(rng, months_ff5, ff5, 4.0),
            _factor_rows(rng, years[37:], ff5, 15.0),
        ),
        encoding="utf-8",
    )
    (out / "F-F_Research_Data_5_Factors_2x3_daily.CSV").write_text(
        daily_file(
            ["This file was created by CMPT_ME_BEME_OP_INV_RETS using the 202412 CRSP database."],
            ff5,
            _factor_rows(rng, days, ff5, 0.8),
        ),
        encoding="utf-8",
    )
    (out / "F-F_Momentum_Factor.CSV").write_text(
        file(
            ["This file was created by CMPT_ME_PRIOR_RETS using the 202412 CRSP database."],
            mom,
            _factor_rows(rng, months_ff3[6:], mom, 4.0),
            _factor_rows(rng, years, mom, 15.0),
        ),
        encoding="utf-8",
    )
    (out / "F-F_Momentum_Factor_daily.CSV").write_text(
        daily_file(
            ["This file was created by CMPT_ME_PRIOR_RETS using the 202412 CRSP database."],
            mom,
            _factor_rows(rng, days, mom, 0.8),
        ),
        encoding="utf-8",
    )
    (out / "meta.json").write_text(
        json.dumps(
            {
                "recorded_at": None,
                "synthesized_at": datetime.now(UTC).isoformat(),
                "provider": "ken_french",
                "note": "synthesized in the Data Library's multi-table CSV layout; "
                "the July 1926 FF3 row carries the published values; see tests/fixtures/README.md",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    write_yfinance(rng)
    write_fred(rng)
    write_ecb(rng)
    write_ken_french(rng)
    print(f"fixtures written under {ROOT}")


if __name__ == "__main__":
    main()
