"""World Bank commodity prices — Australian beef (85% visual lean, FOB USD/kg).

Free, no key, no registration. The World Bank "Pink Sheet" publishes monthly commodity
prices including Australian beef, which is the closest freely available proxy for the
90CL/VL market when USDA AMS data isn't accessible.

Series used:
  PBEEF_USD  — Beef, Australian and New Zealand, 85% lean, FOB (USD/kg)

The series is monthly, published with a 1-2 month lag. Values are stored alongside any
USDA AMS data in the same ``lean_beef_prices`` table under grade="WB 85VL".
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from .. import db

TABLE = "lean_beef_prices"
# World Bank v2 API — commodity price indicator, source 89 = GEM Commodities.
BASE = "https://api.worldbank.org/v2/en/indicator"
INDICATOR = "PBEEF_USD"
# All-country aggregate "WLD" holds the Pink Sheet series.
COUNTRY = "WLD"
GRADE = "WB 85VL"
SERIES = "World Bank Pink Sheet"


def fetch(start_year: int, end_year: int) -> pd.DataFrame:
    url = f"{BASE}/{INDICATOR}"
    params = {
        "country": COUNTRY,
        "format": "json",
        "date": f"{start_year}:{end_year}",
        "per_page": 500,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    # WB v2 returns [metadata, [rows]].
    if not isinstance(body, list) or len(body) < 2:
        return pd.DataFrame()
    rows = body[1] or []
    records = []
    for r in rows:
        if r.get("value") is None:
            continue
        # Monthly: "2024M01", "2024M02" … Annual fallback: "2024"
        raw_date = str(r.get("date", ""))
        try:
            if "M" in raw_date:
                d = dt.datetime.strptime(raw_date, "%YM%m").date()
            else:
                d = dt.date(int(raw_date), 1, 1)
        except ValueError:
            continue
        records.append({
            "result_date": d.isoformat(),
            "value": float(r["value"]),
            "grade": GRADE,
            "series": SERIES,
            "unit": "USD/kg",
            "currency": "USD",
        })
    return pd.DataFrame(records)


def ingest(start: str = "2010-01-01") -> int:
    start_year = dt.date.fromisoformat(start).year
    end_year = dt.date.today().year
    df = fetch(start_year, end_year)
    if df.empty:
        print("  World Bank beef: no data returned")
        return 0
    written = db.upsert(TABLE, df, pk=["grade", "series", "result_date"])
    db.export_parquet(TABLE)
    print(f"  World Bank beef ({GRADE}): {written} rows "
          f"({df['result_date'].min()} -> {df['result_date'].max()})")
    return written
