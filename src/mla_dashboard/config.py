"""Central configuration: API base, paths, and the registry of data series to ingest.

Each entry in REPORTS describes one MLA report endpoint, how to call it, and how its
rows map onto a normalised SQLite table. Field names were confirmed against the live
API (https://api-mlastatistics.mla.com.au) and the OpenAPI spec at
https://app.nlrsreports.mla.com.au/static/openapi.yaml.
"""

from __future__ import annotations

from pathlib import Path

# --- API ---
BASE_URL = "https://api-mlastatistics.mla.com.au"
PAGE_SIZE = 100  # API returns ~100 rows/page; used to decide if another page exists.
# Politeness delay between every call. MLA publishes no numeric rate limit and returns no
# rate-limit headers; it warns only that abuse -> throttling/blacklisting. 1s sequential
# spacing keeps a full backfill to a few hundred calls over minutes from a single IP.
# Override with env MLA_REQUEST_DELAY_S to go slower if ever throttled.
import os as _os
REQUEST_DELAY_S = float(_os.environ.get("MLA_REQUEST_DELAY_S", "1.0"))
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 5

# --- Paths ---
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mla.db"
PARQUET_DIR = DATA_DIR / "parquet"

# Earliest date used for a cold backfill when a table is empty. The API may return less
# history than this; the actual earliest date is logged during backfill.
# Cold-backfill start. The MLA API is slow on deep historical queries (~5s/page), so a
# full 2010-> pull takes ~1h. Override with env BACKFILL_START (e.g. 2022-01-01) for a
# faster, shorter-history fill.
BACKFILL_START = _os.environ.get("BACKFILL_START", "2010-01-01")

# Currency each report's price values are denominated in. AU indicators are AUD cents;
# Steiner global/US series are USD. Non-price reports use None.
AUD = "AUD"
USD = "USD"


# --- Report registry -------------------------------------------------------------------
# Keys:
#   report:     endpoint id under /report/<id>
#   table:      destination SQLite table
#   date_field: JSON field holding the row date
#   value_field:JSON field holding the numeric value (price/volume)
#   currency:   AUD / USD / None
#   columns:    JSON field -> SQLite column mapping (excluding date/value handled above)
#   pk:         natural-key columns for idempotent upsert
#   params:     static query params (besides date range / page)
#   date_params:True if the endpoint accepts fromDate/toDate (drives incremental refresh)
#   fanout:     optional (param_name, [values]) to call the endpoint once per value
#               (e.g. one call per indicatorID or countryID). Values resolved at runtime
#               for indicators; static for categories/countries.
REPORTS: dict[str, dict] = {
    "indicators": {
        "report": 5,
        "table": "indicators",
        "date_field": "calendar_date",
        "value_field": "indicator_value",
        "currency": AUD,
        "columns": {
            "indicator_id": "indicator_id",
            "indicator_desc": "indicator_desc",
            "species_id": "species_id",
            "indicator_units": "units",
            "head_count": "head_count",
        },
        "pk": ["indicator_id", "calendar_date"],
        "date_params": True,
        "fanout": ("indicatorID", "indicators"),  # resolved from /indicator at runtime
    },
    "yardings": {
        "report": 4,
        "table": "yardings",
        "date_field": "result_date",
        "value_field": "head_count",
        "currency": None,
        "columns": {
            "category_desc": "category",
            "state_id": "state_id",
            "saleyard_id": "saleyard_id",
            "tranx_type_id": "tranx_type",
        },
        "pk": ["category", "state_id", "saleyard_id", "tranx_type", "result_date"],
        "date_params": True,
        "fanout": ("category", ["Cattle", "Sheep", "Lamb", "Goat"]),
    },
    "slaughter_production": {
        "report": 3,
        "table": "slaughter_production",
        "date_field": "report_date",
        "value_field": "value_amt",
        "currency": None,
        "columns": {
            "report_type": "report_type",
            "category": "category",
            "location_id": "location_id",
            "unit_of_measure": "unit",
        },
        "pk": ["report_type", "category", "location_id", "report_date"],
        "date_params": True,
    },
    "nlrs_slaughter": {
        "report": 10,
        "table": "nlrs_slaughter",
        "date_field": "result_date",
        "value_field": "slaughter_count",
        "currency": None,
        "columns": {
            "contributor_state_id": "state_id",
            "species_id": "species_id",
        },
        "pk": ["state_id", "species_id", "result_date"],
        "date_params": True,
    },
    "exports": {
        "report": 1,
        "table": "exports",
        "date_field": "result_date",
        "value_field": "weight_amt",
        "currency": None,
        "columns": {
            "country_desc": "country",
            "meat_type_group_desc": "meat_type",
        },
        "pk": ["country", "meat_type", "result_date"],
        "date_params": True,
    },
    "global_cattle_prices": {
        "report": 7,
        "table": "global_cattle_prices",
        "date_field": "indicator_date",
        "value_field": "indicator_value",
        "currency": USD,
        "columns": {
            "country_code": "country_code",
            "indicator_desc": "indicator_desc",
            "indicator_units": "units",
            "species_id": "species_id",
        },
        "pk": ["country_code", "indicator_desc", "indicator_date"],
        "date_params": True,
        # Steiner country codes; probed empirically (USA confirmed). Unknowns return
        # empty and are skipped harmlessly.
        "fanout": ("countryID", ["USA", "CAN", "BRA", "ARG", "URY", "NZL", "EU"]),
    },
}

# Reports 2 (herd) uses year/stateID/category instead of date range; handled separately
# in ingest_mla.ingest_herd().
HERD_TABLE = "herd_flock"
