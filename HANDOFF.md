# HANDOFF — MLA dashboard data refresh (resume tomorrow)

**Date paused:** 2026-06-17 ~22:15 local
**Branch:** main

## Goal
Full data refresh via `python -m mla_dashboard.refresh --backfill`, then commit refreshed
parquet to `data/parquet/` and push to main. Backfill was paused partway; this doc covers
what's done, what's left, and gotchas.

## Step 1 — MLA API probe (DONE)
Ran `python probe_mla_reports.py` to look for 90CL / lean / manufacturing beef in the MLA API.

| Report | Result | Lean/90CL? |
|--------|--------|-----------|
| 6      | 500 error from `/report/6` | — |
| 8      | 78 rows — "CME Feeder Cattle Index", US c/lb lwt | No (cattle futures index) |
| 9      | 148 rows — "Steer Flats", US c/lb | No (steer price) |
| 11–20  | 403 Forbidden (no access) | — |

**Conclusion: no MLA report holds 90CL/lean/manufacturing beef.** Reports 8/9 are live but are
cattle/steer price indices, not lean beef. Nothing flagged interesting by the probe.

=> **Step 3 (add report to `config.py REPORTS`) is SKIPPED** — no qualifying report exists.
90CL/lean beef must keep coming from the external USDA AMS source (`external/usda_ams.py`),
not MLA.

## Step 2 — Backfill (PARTIAL — RESUME HERE)
Run env: package not installed, so **must** set `PYTHONPATH=src`:
```
PYTHONPATH=src python -m mla_dashboard.refresh --backfill
```
(Plain `python -m mla_dashboard.refresh` fails: `ModuleNotFoundError: No module named
'mla_dashboard'`. Package lives under `src/`, not pip-installed. Fix permanently with
`pip install -e .` if desired.)

Refresh order (see `refresh.py`): reference → indicators → yardings → slaughter_production →
nlrs_slaughter → exports → global_cattle_prices → herd → fx → usda_psd → usda_ams(90CL) →
worldbank → abs. `export_parquet` runs once per table at that table's completion.

### Done this run (in DB + parquet, committed):
- ref_indicator (114), ref_saleyard (642)
- indicators (100,537) — full 2010→ backfill
- yardings (42,335)

### Stale-but-committed (unchanged from prior runs, data already present):
- slaughter_production (2,064), nlrs_slaughter (8,459), exports (583),
  global_cattle_prices (462), fx_rates (1,139)

### NOT YET RUN — pending tomorrow:
- **herd_flock** (report 2, year-based) — table does not exist yet
- **usda_psd** (USDA PSD) — table does not exist yet
- **usda_ams 90CL/VL** (lean beef) — `lean_beef_prices` table does not exist yet
- **worldbank** (85VL beef) — writes to `lean_beef_prices`
- **abs** (ABS) — pending

## Tomorrow's plan
1. `PYTHONPATH=src python -m mla_dashboard.refresh --backfill` again.
   - Idempotent: completed tables (indicators/yardings) upsert on natural PK, no dupes.
   - Backfill is slow (~1h); indicators is the slow part. Stdout is buffered when not a tty —
     watch progress via DB growth: `ls -la data/mla.db` and per-table row counts instead.
2. Confirm new tables populated: herd_flock, usda_psd, lean_beef_prices.
3. Re-export any tables if needed, then commit `data/parquet/` + push to main.
4. Report per-source row counts and any `skip ...` lines (API errors) from the run.

## Gotchas
- `data/mla.db` (~16 MB) is git-tracked but we commit **only `data/parquet/`** per the task.
  Leave mla.db unstaged.
- A Streamlit dashboard process may be running separately — don't kill it.
- `ps -W` PID column ≠ Windows PID; use the WINPID (4th col) for taskkill, or `TaskStop`.
- Tonight's snapshot is PARTIAL — main has indicators/yardings refreshed but NOT herd or any
  external (fx is stale, 90CL/PSD/worldbank/abs absent). Do not treat as complete.
