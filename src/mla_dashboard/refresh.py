"""Incremental refresh orchestrator.

For each registry report: read the latest stored date, then pull from that date forward
(re-pulling the last day to capture revisions). Empty tables trigger a cold backfill from
config.BACKFILL_START. Runnable from Windows Task Scheduler.

Usage:
    python -m mla_dashboard.refresh            # incremental top-up
    python -m mla_dashboard.refresh --backfill # force full history pull
"""

from __future__ import annotations

import argparse
import datetime as dt

from . import config, db
from .client import MLAClient
from .external import abs as abs_ext
from .external import abs_cpi, fx, mla_us_imported, usda_ams, usda_psd, worldbank
from .ingest_mla import ingest_herd, ingest_reference, ingest_report


def _from_date(table: str, date_field: str, backfill: bool) -> str:
    if backfill:
        return config.BACKFILL_START
    latest = db.max_date(table, date_field)
    return latest or config.BACKFILL_START


def run(backfill: bool = False) -> None:
    client = MLAClient()
    today = dt.date.today().isoformat()
    print(f"Refresh start ({'backfill' if backfill else 'incremental'}) -> {today}")

    ingest_reference(client)

    for key, spec in config.REPORTS.items():
        if not spec.get("date_params"):
            continue
        start = _from_date(spec["table"], spec["date_field"], backfill)
        n = ingest_report(client, key, start, today)
        print(f"  {key}: {n} rows ({start}..{today})")

    # Herd report: pull the span of years covered by the date window.
    start_year = int(config.BACKFILL_START[:4]) if backfill else dt.date.today().year - 2
    years = list(range(start_year, dt.date.today().year + 1))
    print(f"  herd_flock: {ingest_herd(client, years)} rows ({years[0]}..{years[-1]})")

    # External sources (each skips gracefully on error / missing key).
    print(f"  fx_rates: {fx.ingest(config.BACKFILL_START if backfill else _from_date('fx_rates', 'date', False))} rows")
    print(f"  usda_psd: {usda_psd.ingest(years)} rows")
    # Steiner 90CL/trim via MLA report 9: keyless, so this is the 90CL series that actually
    # refreshes unattended. Tops up from its own latest date, not the table-wide maximum,
    # since lean_beef_prices also holds the manual MLA series and USDA AMS rows.
    steiner_start = config.BACKFILL_START if backfill else (
        db.max_date("lean_beef_prices", "result_date", "series", mla_us_imported.SERIES)
        or config.BACKFILL_START
    )
    print(f"  mla_us_imported (90CL/trim): "
          f"{mla_us_imported.ingest(steiner_start, today, client)} rows ({steiner_start}..)")
    ams_start = config.BACKFILL_START if backfill else (_from_date("lean_beef_prices", "result_date", False))
    print(f"  usda_ams (90CL/VL): {usda_ams.ingest(ams_start)} rows")
    wb_start = config.BACKFILL_START if backfill else (_from_date("lean_beef_prices", "result_date", False))
    print(f"  worldbank (85VL beef): {worldbank.ingest(wb_start)} rows")
    print(f"  abs: {abs_ext.ingest()} rows")
    # CPI is republished in full each release, so always re-pull the whole span rather than
    # topping up: revisions to earlier periods are picked up by the upsert.
    print(f"  abs_cpi: {abs_cpi.ingest()} rows")
    print("Refresh complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh MLA dashboard data")
    parser.add_argument("--backfill", action="store_true", help="force full history pull")
    run(parser.parse_args().backfill)


if __name__ == "__main__":
    main()
