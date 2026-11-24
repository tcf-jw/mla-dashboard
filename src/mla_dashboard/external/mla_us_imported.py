"""US imported meat prices (MLA report 9, sourced from US Steiner Consulting).

This is the automated 90CL source. Report 9 publishes ~12 imported lean/trim grades and
cuts in **US c/lb**, weekly (Tuesday), with history back to 2000 - including
"90CL Boneless Beef, NZ/Australia", the headline imported grinding-beef price that
``mla_90cl_manual`` previously supplied only via a hand-exported spreadsheet.

It needs no API key, unlike ``usda_ams``, so it runs unattended in CI.

Rows land in ``lean_beef_prices`` under their own ``series`` so they sit alongside (never
overwrite) the manual MLA import-parity series and any USDA AMS rows. ``grade`` holds the
full Steiner indicator name because two distinct 90CL quotes exist (NZ, and NZ/Australia)
and they must not collide on the natural key.

MLA's published AUD import-parity number is this series converted at the day's AUD/USD
rate and lb->kg: ``US c/lb * 2.20462 / aud_usd``. That reproduces the manual spreadsheet to
within ~0.3% (MLA converts on RBA rates, the dashboard's ``fx_rates`` come from the ECB via
Frankfurter), so both are kept and can be cross-checked against each other.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .. import analysis, config, db
from ..client import MLAApiError, MLAClient
from ..ingest_mla import year_chunks
from . import mla_90cl_manual

REPORT_ID = 9
TABLE = "lean_beef_prices"
SERIES = "US imported (Steiner, weekly)"
DERIVED_SERIES = "MLA imported 90CL (derived, weekly)"
PARITY_GRADE = "90CL Boneless Beef, NZ/Australia"


def _normalise(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        name, date, value = (
            r.get("indicator_name"),
            r.get("indicator_date"),
            r.get("indicator_value"),
        )
        if not (name and date and value not in (None, "")):
            continue
        try:
            value = float(str(value).replace(",", ""))
        except ValueError:
            continue
        out.append({
            "result_date": pd.to_datetime(date).strftime("%Y-%m-%d"),
            "value": value,
            "grade": name,
            "series": SERIES,
            "unit": r.get("indicator_units") or "US c/lb",
            "currency": "USD",
        })
    return pd.DataFrame(out)


def ingest(
    start: str = config.BACKFILL_START,
    end: str | None = None,
    client: MLAClient | None = None,
) -> int:
    """Pull report 9 over [start, end], chunked by year.

    Multi-year windows 504 on this endpoint, and any window whose ``toDate`` runs past the
    latest published week 500s outright, so each year is fetched separately and a rejected
    tail is retried up to the last end date the API will accept.
    """
    client = client or MLAClient()
    end = end or dt.date.today().isoformat()
    written = 0
    for cf, ct in year_chunks(start, end):
        try:
            rows = client.get_all(REPORT_ID, {"fromDate": cf, "toDate": ct})
        except MLAApiError as e:
            good = client.last_good_to(REPORT_ID, {}, cf, ct)
            if good is None:
                print(f"  skip US imported {cf}..{ct}: no data ({e})")
                continue
            if good != ct:
                print(f"  US imported: API rejects past {good}; pulling {cf}..{good}")
            try:
                rows = client.get_all(REPORT_ID, {"fromDate": cf, "toDate": good})
            except MLAApiError as e2:
                print(f"  skip US imported {cf}..{good}: {e2}")
                continue
        written += db.upsert(TABLE, _normalise(rows), pk=["grade", "series", "result_date"])
    db.export_parquet(TABLE)
    return written


def derive_aud_90cl() -> int:
    """Rebuild MLA's AUD import-parity 90CL from the Steiner quote, every refresh.

    The manual series only moves when someone re-exports the portal xlsx (it stalled at
    2026-06-05), so this keeps an AUD c/kg 90CL current: ``US c/lb * 2.20462 / aud_usd``
    on date-matched FX. It lands as grade "90CL" under its own ``series`` beside the manual
    one, and is refused if the two disagree on their shared weeks by more than 2% on
    average (a units or FX fault), so a wrong number never ships.
    """
    # Read the merged snapshot, not mla.db: CI's cold-start DB never holds the manual
    # series, so the cross-check would have nothing to compare against.
    path = config.PARQUET_DIR / f"{TABLE}.parquet"
    fx = analysis.load_fx()
    if not path.exists() or fx.empty:
        return 0
    lb = pd.read_parquet(path)
    src = lb[(lb["series"] == SERIES) & (lb["grade"] == PARITY_GRADE)]
    # FX starts 2009-12-31; "nearest" matching would price earlier weeks at that rate.
    src = src[pd.to_datetime(src["result_date"]) >= fx["date"].min()]
    aud, _ = analysis.to_per_kg(analysis.to_currency(src, "AUD", "result_date"))
    out = aud.assign(
        result_date=aud["result_date"].dt.strftime("%Y-%m-%d"),
        grade="90CL", series=DERIVED_SERIES, unit="AU c/kg", currency="AUD",
    )[["result_date", "value", "grade", "series", "unit", "currency"]]

    manual = lb.loc[lb["series"] == mla_90cl_manual.SERIES, ["result_date", "value"]]
    both = out.merge(manual, on="result_date", suffixes=("", "_manual"))
    if not both.empty:
        gap = (both["value"] / both["value_manual"] - 1).abs().mean() * 100
        print(f"  derived AUD 90CL vs manual: {gap:.2f}% mean gap over {len(both)} weeks")
        if gap > 2:
            print("  WARNING: derived AUD 90CL disagrees with the manual series; not written")
            return 0

    written = db.upsert(TABLE, out, pk=["grade", "series", "result_date"])
    db.export_parquet(TABLE)
    return written


def main() -> None:
    print(f"MLA US imported (report 9): {ingest()} rows -> {TABLE}")


if __name__ == "__main__":
    main()
