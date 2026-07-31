"""ABS livestock slaughter & meat production: the official quarterly series.

Uses the ABS Data API (SDMX, no key). Two dataflows are pulled:

* ``LSTOCK_SLAUGHT`` - livestock slaughtered (head), by category: cattle, calves, sheep,
  lambs, pigs, chickens.
* ``LSTOCK_MEAT`` - meat produced (tonnes), by type: beef, veal, lamb, mutton, pig meat,
  chicken meat, total red meat.

Between them these are the only pig and poultry numbers in the dashboard: MLA's API covers
cattle, sheep and goats only. Both are quarterly, by state and for Australia as a whole.

The API lives under ``/rest``; the bare ``/data`` path 403s, and the dataflow ids are
``LSTOCK_*`` (an earlier ``LIVESTOCK_MEAT`` guess 404s). If a request fails the step is
skipped without breaking the pipeline.

Docs: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
"""

from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

from .. import db

BASE = "https://data.api.abs.gov.au/rest"
TABLE = "ext_abs_slaughter"

# dataflow id -> (dataset label, the flow's own category dimension column)
DATAFLOWS = {
    "LSTOCK_SLAUGHT": ("Livestock slaughtered", "Livestock slaughtered"),
    "LSTOCK_MEAT": ("Meat produced", "Meat produced"),
}


def _normalise(csv_text: str, dataset: str, category_col: str) -> pd.DataFrame:
    raw = pd.read_csv(StringIO(csv_text), low_memory=False)
    if raw.empty or category_col not in raw.columns:
        return pd.DataFrame()
    period = raw["TIME_PERIOD"].astype(str)
    # Quarterly periods ("2024-Q1") are stored as the quarter's last day so they align
    # with the daily price series on a shared time axis.
    period_end = pd.PeriodIndex(period, freq="Q").to_timestamp(how="end").normalize()
    # OBS_VALUE is scaled by UNIT_MULT (a power of ten) where present, e.g. thousands.
    # LSTOCK_MEAT omits the column entirely, so default to 10^0.
    mult = pd.to_numeric(raw["UNIT_MULT"], errors="coerce").fillna(0) if "UNIT_MULT" in raw else 0
    out = pd.DataFrame({
        "period_end": period_end.strftime("%Y-%m-%d"),
        "period": period,
        "dataset": dataset,
        "category": raw[category_col],
        "state": raw["State"],
        "value": pd.to_numeric(raw["OBS_VALUE"], errors="coerce") * (10.0 ** mult),
        "unit": raw["Unit of Measure"],
    })
    return out.dropna(subset=["value"])


def ingest(start_period: str = "1990") -> int:
    written = 0
    for flow, (dataset, category_col) in DATAFLOWS.items():
        url = f"{BASE}/data/{flow}/all"
        params = {"startPeriod": start_period, "format": "csvfilewithlabels"}
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ABS {flow}: {e} (skipping)")
            continue
        df = _normalise(resp.text, dataset, category_col)
        written += db.upsert(TABLE, df, pk=["dataset", "category", "state", "period"])
    if written:
        db.export_parquet(TABLE)
    return written


def main() -> None:
    print(f"ABS livestock: {ingest()} rows -> {TABLE}")


if __name__ == "__main__":
    main()
