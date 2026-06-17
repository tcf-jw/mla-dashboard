"""Fetch MLA reports, normalise to tidy frames, and upsert into SQLite.

The generic ``ingest_report`` drives every date-ranged report from the config registry.
Reference tables and the herd report (which uses year/state params) are handled by their
own small functions.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from . import config, db
from .client import MLAClient, MLAApiError


def _year_chunks(from_date: str, to_date: str):
    """Yield [start, end] ISO date pairs, one per calendar year.

    The MLA API returns HTTP 500 on wide date ranges, so requests must be split into
    yearly windows.
    """
    start = dt.date.fromisoformat(from_date)
    end = dt.date.fromisoformat(to_date)
    for year in range(start.year, end.year + 1):
        a = max(start, dt.date(year, 1, 1))
        b = min(end, dt.date(year, 12, 31))
        if a <= b:
            yield a.isoformat(), b.isoformat()


def _normalise(rows: list[dict], spec: dict) -> pd.DataFrame:
    """Map raw JSON rows to the table schema: date_col, value, currency, + mapped cols."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame()
    date_col = spec["date_field"]
    out[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    out["value"] = pd.to_numeric(df[spec["value_field"]], errors="coerce")
    for src, dest in spec["columns"].items():
        out[dest] = df[src] if src in df.columns else None
    if spec["currency"]:
        out["currency"] = spec["currency"]
    return out


def resolve_indicator_ids(client: MLAClient) -> list[str]:
    return [str(r["indicator_id"]) for r in client.get_reference("/indicator")]


def ingest_report(client: MLAClient, key: str, from_date: str, to_date: str) -> int:
    """Ingest one registry report over [from_date, to_date], chunked by year.

    Fans out over the report's optional parameter (indicatorID / category / countryID)
    and splits each into yearly windows to avoid the API's wide-range 500s.
    """
    spec = config.REPORTS[key]
    written = 0

    fanout = spec.get("fanout")
    if fanout:
        param_name, values = fanout
        if values == "indicators":
            values = resolve_indicator_ids(client)
        fan_params = [{param_name: v} for v in values]
    else:
        fan_params = [{}]

    for fp in fan_params:
        for cf, ct in _year_chunks(from_date, to_date):
            params = {**fp, "fromDate": cf, "toDate": ct}
            try:
                rows = client.get_all(spec["report"], params)
            except MLAApiError as e:
                print(f"  skip {key} {params}: {e}")
                continue
            written += db.upsert(spec["table"], _normalise(rows, spec), spec["pk"])
    db.export_parquet(spec["table"])
    return written


def ingest_reference(client: MLAClient) -> None:
    """Cache /indicator and /saleyard reference tables."""
    for path, table in (("/indicator", "ref_indicator"), ("/saleyard", "ref_saleyard")):
        rows = client.get_reference(path)
        if rows:
            db.upsert(table, pd.DataFrame(rows), pk=[])
            db.export_parquet(table)


def ingest_herd(client: MLAClient, years: list[int]) -> int:
    """Report 2 (herd & flock) uses year params rather than a date range."""
    written = 0
    for year in years:
        try:
            rows = client.get_all(2, {"year": year})
        except MLAApiError as e:
            print(f"  skip herd {year}: {e}")
            continue
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["year"] = year
        written += db.upsert(config.HERD_TABLE, df, pk=list(df.columns))
    db.export_parquet(config.HERD_TABLE)
    return written
