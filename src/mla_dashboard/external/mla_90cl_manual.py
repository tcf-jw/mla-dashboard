"""Manual import of MLA's indicative imported 90CL price (AUD c/kg, weekly).

MLA's public API exposes no 90CL/lean-beef report, so this headline grinding-beef series
is brought in from a hand-exported spreadsheet pulled from MLA's market-data portal
(``data-manual/Imported 90CL Price - Historical.xlsx``): "90CL Boneless Beef, NZ/Australia",
CIF, weekly average, in Australian cents/kg.

It lands in the same ``lean_beef_prices`` table the dashboard's 90CL/VL tab reads, as its
own ``series`` so it sits alongside (never overwrites) the USDA AMS US negotiated series.
This is a manual step — not part of the automated ``refresh`` run — because the source is a
periodic manual export, not an API:

    python -m mla_dashboard.external.mla_90cl_manual

Re-running is idempotent (upsert on grade/series/result_date).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import config, db

TABLE = "lean_beef_prices"
SERIES = "MLA imported 90CL (weekly)"
GRADE = "90CL"
DEFAULT_XLSX = config.ROOT / "data-manual" / "Imported 90CL Price - Historical.xlsx"


def _parse(xlsx: Path) -> pd.DataFrame:
    """Pull (date, value, unit) rows from the portal export.

    The sheet carries a filter banner and a grand-total row above the data, so columns are
    unnamed: read headerless and keep only rows whose first column is a real date and whose
    second is numeric. That drops the banner, the header row, and the dateless total row.
    """
    raw = pd.read_excel(xlsx, header=None)
    date = pd.to_datetime(raw[0], errors="coerce")
    value = pd.to_numeric(raw[1], errors="coerce")
    keep = date.notna() & value.notna()
    return pd.DataFrame({
        "result_date": date[keep].dt.strftime("%Y-%m-%d"),
        "value": value[keep],
        "grade": GRADE,
        "series": SERIES,
        "unit": raw.loc[keep, 2].fillna("AU c/kg"),
        "currency": "AUD",
    })


def ingest(xlsx: str | Path = DEFAULT_XLSX) -> int:
    xlsx = Path(xlsx)
    if not xlsx.exists():
        print(f"  MLA 90CL manual: {xlsx} not found, skipping")
        return 0
    df = _parse(xlsx)
    written = db.upsert(TABLE, df, pk=["grade", "series", "result_date"])
    db.export_parquet(TABLE)
    return written


def main() -> None:
    print(f"MLA 90CL manual import: {ingest()} rows -> {TABLE}")


if __name__ == "__main__":
    main()
