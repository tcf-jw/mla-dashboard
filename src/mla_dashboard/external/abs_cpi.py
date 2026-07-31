"""ABS Consumer Price Index: headline CPI and the full category tree.

Pulls the ABS ``CPI`` dataflow over the SDMX Data API (no key). The slice kept is the
headline one: Australia-wide, original (not seasonally adjusted), both index numbers and
annual percentage change, at whatever frequency each series publishes (the CPI is
quarterly; a monthly indicator series runs alongside it from 2018).

Every ``INDEX`` code is kept, so the table holds All groups CPI down to individual
expenditure classes: Food and non-alcoholic beverages, Meat and seafoods, and single
commodities including Beef and veal, Lamb and goat, Pork and Poultry. Those meat lines are
retail price indices, not farmgate prices, which makes them the consumer-side counterpart
to the saleyard indicators.

Docs: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
"""

from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

from .. import db

BASE = "https://data.api.abs.gov.au/rest"
DATAFLOW = "CPI"
TABLE = "cpi"

# SDMX data key, dimensions in order: MEASURE.INDEX.TSEST.REGION.FREQ
#   MEASURE 1 = index numbers, 3 = percentage change from previous year
#   INDEX   (blank) = every category
#   TSEST   10 = original
#   REGION  50 = Australia
#   FREQ    (blank) = monthly and quarterly
DATA_KEY = "1+3..10.50."

# ABS periods are "2026-Q1" (quarterly) or "2026-01" (monthly). Both are stored as the
# period's last day so CPI lines up against daily price series on a shared time axis.
START_PERIOD = "1990-Q1"


def _to_period_end(period: pd.Series) -> pd.Series:
    quarterly = period.str.contains("Q", na=False)
    out = pd.Series(pd.NaT, index=period.index, dtype="datetime64[ns]")
    if quarterly.any():
        out[quarterly] = pd.PeriodIndex(period[quarterly], freq="Q").to_timestamp(how="end").normalize()
    if (~quarterly).any():
        out[~quarterly] = pd.PeriodIndex(period[~quarterly], freq="M").to_timestamp(how="end").normalize()
    return out.dt.strftime("%Y-%m-%d")


def _normalise(csv_text: str) -> pd.DataFrame:
    raw = pd.read_csv(StringIO(csv_text), low_memory=False)
    if raw.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "period_end": _to_period_end(raw["TIME_PERIOD"].astype(str)),
        "period": raw["TIME_PERIOD"].astype(str),
        "category_id": raw["INDEX"].astype(str),
        "category": raw["Index"],
        "measure": raw["Measure"],
        "freq": raw["Frequency"],
        "value": pd.to_numeric(raw["OBS_VALUE"], errors="coerce"),
        "unit": raw["Unit of Measure"],
    })
    return out.dropna(subset=["value", "period_end"])


def ingest(start_period: str = START_PERIOD) -> int:
    url = f"{BASE}/data/{DATAFLOW}/{DATA_KEY}"
    params = {"startPeriod": start_period, "format": "csvfilewithlabels"}
    try:
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ABS CPI: {e} (skipping)")
        return 0
    df = _normalise(resp.text)
    if df.empty:
        return 0
    written = db.upsert(TABLE, df, pk=["category_id", "measure", "freq", "period"])
    db.export_parquet(TABLE)
    return written


def main() -> None:
    print(f"ABS CPI: {ingest()} rows -> {TABLE}")


if __name__ == "__main__":
    main()
