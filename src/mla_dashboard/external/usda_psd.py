"""USDA PSD Online: global cattle/beef supply & production by country.

Requires a free api.data.gov key in the USDA_PSD_API_KEY environment variable. Without
a key, ``ingest`` is a no-op so the rest of the pipeline still runs.

Docs: https://apps.fas.usda.gov/opendataweb/home
"""

from __future__ import annotations

import os

import pandas as pd
import requests

from .. import db

BASE = "https://apps.fas.usda.gov/OpenData/api/psd"
TABLE = "ext_usda_psd"
# Beef & cattle commodity codes; extend as needed.
COMMODITIES = {"0111000": "Cattle", "0113000": "Beef and Veal"}


def _key() -> str | None:
    return os.environ.get("USDA_PSD_API_KEY")


def _get(path: str) -> list[dict]:
    headers = {"API_KEY": _key(), "Accept": "application/json"}
    resp = requests.get(f"{BASE}{path}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def ingest(years: list[int]) -> int:
    if not _key():
        print("  USDA PSD: no USDA_PSD_API_KEY set, skipping")
        return 0
    written = 0
    for code, name in COMMODITIES.items():
        frames = []
        for year in years:
            try:
                rows = _get(f"/commodity/{code}/country/all/year/{year}")
            except requests.RequestException as e:
                print(f"  USDA PSD {name} {year}: {e}")
                continue
            if rows:
                df = pd.DataFrame(rows)
                df["commodity_name"] = name
                frames.append(df)
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            written += db.upsert(TABLE, combined, pk=list(combined.columns))
    db.export_parquet(TABLE)
    return written
