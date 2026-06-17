"""ABS Livestock & Meat: official Australian slaughter & meat production.

Uses the ABS Data API (SDMX-JSON, no key). The dataflow id for "Livestock and Meat"
is configurable because ABS occasionally re-versions dataflows; if the request fails the
step is skipped without breaking the pipeline.

Docs: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
"""

from __future__ import annotations

import pandas as pd
import requests

from .. import db

BASE = "https://data.api.abs.gov.au"
DATAFLOW = "LIVESTOCK_MEAT"  # ABS livestock slaughter & production dataflow id
TABLE = "ext_abs_slaughter"


def ingest(start_period: str = "2010") -> int:
    url = f"{BASE}/data/{DATAFLOW}/all"
    params = {"startPeriod": start_period, "format": "csvfile"}
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ABS: {e} (skipping)")
        return 0
    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    if df.empty:
        return 0
    written = db.upsert(TABLE, df, pk=list(df.columns))
    db.export_parquet(TABLE)
    return written
