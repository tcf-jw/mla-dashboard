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

### Pending-source health — SMOKE-TESTED 2026-06-18 (window 2025-01-01..2026-06-18, yrs 2025/26)
Tested each pending source at narrow scope before committing to a full backfill. Result:
**5 of 6 are blocked or broken** — a full backfill will NOT pull them. Do not run a full
backfill until these are resolved; it only re-pulls MLA reports (already done) + fx.

| Source | Test result | Blocker / action |
|--------|-------------|------------------|
| fx_rates | ✅ 372 rows | works — no action |
| usda_ams **90CL/VL** | ⛔ skipped | **`USDA_AMS_API_KEY` not set.** Register at https://mymarketnews.ams.usda.gov/ , set env var. This is the headline goal. |
| usda_psd | ⛔ skipped | **`USDA_PSD_API_KEY` not set.** Free key at api.data.gov, set env var. |
| herd_flock | ❌ 0 rows | report 2 (`/report/2?year=Y`) returns 0 rows for 2023/24/25 — endpoint/param drift, needs debugging in `ingest_mla.ingest_herd` / API shape. |
| worldbank 85VL | ❌ no data | `worldbank.ingest` returns nothing even from 2010 — endpoint likely changed, needs debugging. |
| abs | ⛔ 403 | `https://data.api.abs.gov.au/data/LIVESTOCK_MEAT/...` returns 403 Forbidden — auth/endpoint change. |

No `.env` file exists and no USDA/ABS keys are in the environment (checked 2026-06-18).
Smoke-test calls mutated DB/parquet (fx top-up) but were **reverted** (`git restore data/`) —
working tree is clean at the last commit.

## Resume plan (blocked until keys + fixes)
1. **You:** obtain + set `USDA_AMS_API_KEY` (90CL) and `USDA_PSD_API_KEY`. Persist via env or a
   `.env` (confirm the code loads `.env` — currently it only reads `os.environ`).
2. **Debug** the 3 broken/forbidden sources separately (herd report 2, worldbank, abs) — these
   are code/endpoint bugs, independent of the backfill.
3. Re-run the narrow smoke test to confirm each source returns rows.
4. Only then: `PYTHONPATH=src python -m mla_dashboard.refresh --backfill`.
   - Idempotent: completed tables (indicators/yardings) upsert on natural PK, no dupes.
   - Slow (~1h); indicators is the slow part. Stdout buffered when not a tty — watch progress
     via DB growth: `ls -la data/mla.db` + per-table row counts.
5. Confirm new tables populated: herd_flock, usda_psd, lean_beef_prices.
6. Commit `data/parquet/` + push to main. Report per-source row counts + any `skip ...` lines.

## Gotchas
- `data/mla.db` (~16 MB) is git-tracked but we commit **only `data/parquet/`** per the task.
  Leave mla.db unstaged.
- A Streamlit dashboard process may be running separately — don't kill it.
- `ps -W` PID column ≠ Windows PID; use the WINPID (4th col) for taskkill, or `TaskStop`.
- Tonight's snapshot is PARTIAL — main has indicators/yardings refreshed but NOT herd or any
  external (fx is stale, 90CL/PSD/worldbank/abs absent). Do not treat as complete.
