"""USDA AMS (Market News) lean/trim beef prices — the 90CL / VL grinding-beef series.

These are the US negotiated prices for boneless processing beef and beef trimmings by
chemical-lean (CL) / visual-lean (VL) grade — e.g. 90% lean ("90CL"), 85CL, 50CL — which
are the headline reference for Australian export grinding beef. Domestic trimmings track
the imported 90CL price closely, so this is a free, daily-updated proxy for the 90CL
market alongside MLA's own indicative imported series.

Source: USDA AMS MARS API v1.2 (https://mymarketnews.ams.usda.gov/mars-api). A free API
key is required (request at https://mymarketnews.ams.usda.gov/, then set USDA_AMS_API_KEY).
Without a key, ``ingest`` is a no-op so the rest of the pipeline still runs.

Note: ``marsapi.ams.usda.gov`` must be reachable. In a network-restricted environment add
it to the egress allowlist, or run the refresh from a machine with open internet access.
"""

from __future__ import annotations

import datetime as dt
import os
import re

import pandas as pd
import requests

from .. import db

BASE = "https://marsapi.ams.usda.gov/services/v1.2"
TABLE = "lean_beef_prices"

# AMS report slugs that carry boneless processing beef / trimmings by lean grade.
# LM_XB403: National Weekly Boneless Processing Beef & Beef Trimmings — Negotiated Sales.
# LM_XB459: National Daily Boneless Processing Beef & Beef Trimmings — Negotiated Sales.
REPORTS = {
    "LM_XB403": "Weekly negotiated",
    "LM_XB459": "Daily negotiated",
}

# Field-name candidates vary slightly by report; probe each in order.
DATE_FIELDS = ("report_date", "report_begin_date", "published_date")
ITEM_FIELDS = ("item_description", "description", "commodity", "item")
PRICE_FIELDS = ("weighted_average", "wtd_avg", "avg_price", "price_avg", "price")
UNIT_FIELDS = ("price_unit", "unit", "unit_of_measure")

# Keep only rows that name a lean grade (e.g. "90% lean", "90CL", "Beef Trimmings 50%").
LEAN_RE = re.compile(r"(\d{2})\s*%|\b(\d{2})\s*cl\b|\b(\d{2})\s*vl\b", re.IGNORECASE)


def _key() -> str | None:
    return os.environ.get("USDA_AMS_API_KEY")


def _first(row: dict, names: tuple[str, ...]):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def _lean_label(text: str) -> str | None:
    """Normalise an item description to a clean grade label like '90CL'."""
    m = LEAN_RE.search(text or "")
    if not m:
        return None
    pct = next(g for g in m.groups() if g)
    return f"{pct}CL"


def _get(slug: str, start: str, end: str) -> list[dict]:
    """Fetch one AMS report over a date range. Key is the basic-auth username."""
    # MARS query DSL: report_date between two MM/DD/YYYY dates.
    s = dt.date.fromisoformat(start).strftime("%m/%d/%Y")
    e = dt.date.fromisoformat(end).strftime("%m/%d/%Y")
    url = f"{BASE}/reports/{slug}"
    resp = requests.get(
        url, params={"q": f"report_date={s}:{e}"},
        auth=(_key(), ""), headers={"Accept": "application/json"}, timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    # v1.2 wraps rows in "results"; some report shapes return a bare list.
    return body.get("results", body) if isinstance(body, dict) else body


def _normalise(rows: list[dict], series: str) -> pd.DataFrame:
    out = []
    for r in rows:
        date = _first(r, DATE_FIELDS)
        price = _first(r, PRICE_FIELDS)
        item = _first(r, ITEM_FIELDS)
        grade = _lean_label(str(item))
        if not (date and price is not None and grade):
            continue
        try:
            value = float(str(price).replace(",", ""))
        except ValueError:
            continue
        out.append({
            "result_date": pd.to_datetime(date).strftime("%Y-%m-%d"),
            "value": value,
            "grade": grade,
            "series": series,
            "unit": _first(r, UNIT_FIELDS) or "USD/cwt",
            "currency": "USD",
        })
    return pd.DataFrame(out)


def ingest(start: str = "2022-01-01", end: str | None = None) -> int:
    if not _key():
        print("  USDA AMS: no USDA_AMS_API_KEY set, skipping (90CL/VL not pulled)")
        return 0
    end = end or dt.date.today().isoformat()
    written = 0
    for slug, series in REPORTS.items():
        try:
            rows = _get(slug, start, end)
        except requests.RequestException as e:
            print(f"  USDA AMS {slug}: {e}")
            continue
        df = _normalise(rows, series)
        # One price per grade/date/series; idempotent on re-run.
        written += db.upsert(TABLE, df, pk=["grade", "series", "result_date"])
    db.export_parquet(TABLE)
    return written
