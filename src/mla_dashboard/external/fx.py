"""Daily AUD->USD exchange rates for the dashboard's currency toggle.

Uses Frankfurter (https://www.frankfurter.app), a free, key-less ECB-backed FX API.
Rates are business-day only; the dashboard forward-fills to cover weekends/holidays.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from .. import config, db

# Use the canonical .dev/v1 host directly: the .app host issues a 301 redirect that
# breaks the SSL session in some environments.
FRANKFURTER = "https://api.frankfurter.dev/v1"
TABLE = "fx_rates"


def fetch_aud_usd(start: str, end: str) -> pd.DataFrame:
    url = f"{FRANKFURTER}/{start}..{end}"
    resp = requests.get(url, params={"from": "AUD", "to": "USD"}, timeout=30)
    resp.raise_for_status()
    rates = resp.json().get("rates", {})
    records = [{"date": d, "aud_usd": v["USD"]} for d, v in sorted(rates.items())]
    return pd.DataFrame(records)


def ingest(start: str = config.BACKFILL_START, end: str | None = None) -> int:
    end = end or dt.date.today().isoformat()
    df = fetch_aud_usd(start, end)
    written = db.upsert(TABLE, df, pk=["date"])
    db.export_parquet(TABLE)
    return written
