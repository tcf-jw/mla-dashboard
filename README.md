# MLA Pricing & Supply Dashboard

Pulls historical Australian livestock **pricing** and **supply** data from the
[MLA Statistics API](https://www.mla.com.au/prices-markets/statistics/api/), augments it
with global supply/FX data, stores it locally (SQLite + Parquet), and serves an
interactive Streamlit dashboard with an **AUD/USD** toggle.

---

## Quick start

### Run the dashboard (Windows, no terminal)
1. Double-click **`Refresh Data (Full Backfill).bat`** once — pulls all history (a few minutes).
2. Double-click **`Launch Dashboard.vbs`** — starts hidden (no console) and opens your browser.

Keep it updated later: double-click **`Refresh Data.vbs`** (quick incremental pull, popup when done).

### Run from a terminal
```bash
pip install -r requirements.txt
python -m mla_dashboard.refresh --backfill   # first run: full history
streamlit run app.py                         # launch dashboard
python -m mla_dashboard.refresh              # later: incremental top-up
```
`run_dashboard.bat` is a visible-console launcher fallback.

---

## Using the dashboard

Tabs:
- **Prices** — AU indicators (EYCI etc.), with latest-value + 1-month change KPIs.
- **Supply** — slaughter/production by category, location, measure.
- **Supply/Price** — dual-axis price vs slaughter/production volume, **filtered by
  species** (Cattle / Sheep). Price indicators carry a `species_id` and supply rows a
  `category`, so both sides filter to the same species; shows their correlation.
- **Global** — AU vs world cattle prices.
- **Exports** — top destination markets (selectable N).
- **90CL/VL** — US lean / trim beef prices by chemical-lean grade (90CL, 85CL, 50CL …),
  the reference for Australian export grinding beef. Source: USDA AMS (see below).
- **Analysis** — AU–global spread + correlation.

Every chart has a **⬇ Download CSV** button, and the **sidebar** shows per-dataset **data
freshness** (latest date held).

**Currency:** radio in the **sidebar** (AUD/USD) — re-prices every chart via **date-matched**
FX (a 2015 price uses the 2015 rate, not today's).

**Chart controls:**
- **Frequency** — native radio above each chart (**Daily / Weekly / Monthly / Yearly**).
  Method is automatic: **prices averaged**, **volumes summed** per period.
- **Range** buttons on the chart (**1M / 3M / 6M / 1Y / ALL**) zoom the x-axis;
  pinch/drag for finer zoom. ALL = full history.
- **Unified hover** — point anywhere along the x-axis and a floating box lists every
  series' value for that day; a spike line marks the date.

The layout is responsive: on a phone the currency/freshness controls collapse into the
sidebar, the frequency radio gives large tap targets, and the legend sits below the chart.

---

## Hosting it online

GitHub Pages **cannot** run this — Pages is static-only and Streamlit needs a live Python
process. Use **[Streamlit Community Cloud](https://streamlit.io/cloud)** (free): point it
at this GitHub repo and `app.py`; it runs the app and serves a public URL.

The repo commits `data/parquet/` (a few MB — well under GitHub limits) and the app reads
Parquet when no local `mla.db` is present, so the committed data is all the cloud needs.
The local `mla.db` is git-ignored. Workflow: refresh locally → commit updated Parquet →
cloud auto-redeploys.

---

## Data sources

| Source | What | Auth |
|--------|------|------|
| MLA Statistics API (`api-mlastatistics.mla.com.au`) | AU indicators (EYCI etc.), slaughter & production, herd & flock, yardings, NLRS slaughter, red meat exports, global cattle prices | None |
| Frankfurter (`api.frankfurter.dev`) | Daily AUD/USD FX for currency conversion | None |
| USDA PSD Online | Global cattle/beef supply by country | free `api.data.gov` key |
| USDA AMS Market News (`marsapi.ams.usda.gov`) | **90CL / VL lean & trim beef prices** (grinding-beef reference) | free MARS API key |
| ABS Data API | Official AU slaughter & meat production | None |

Set the optional keys before refreshing:
- Global supply: `export USDA_PSD_API_KEY=your_key` (PowerShell: `$env:USDA_PSD_API_KEY="your_key"`).
- 90CL/VL lean beef: request a free key at <https://mymarketnews.ams.usda.gov/> then
  `export USDA_AMS_API_KEY=your_key` (PowerShell: `$env:USDA_AMS_API_KEY="your_key"`).
  Without it, the refresh skips the 90CL/VL pull and the tab shows an empty state.

### Running in a restricted network (Claude Code on the web, locked-down CI)

The refresh reaches out to the hosts above. In a sandboxed environment with an **egress
allowlist** these calls return `403 Host not in allowlist`. To pull data either:
1. **Add the hosts to the egress allowlist** — at minimum `api-mlastatistics.mla.com.au`,
   `api.frankfurter.dev`, and (for 90CL/VL) `marsapi.ams.usda.gov`; or
2. **Run the refresh on a machine with open internet**, then commit the updated
   `data/parquet/` so the deployed app picks it up.

**API constraint:** the MLA API paginates at ~100 rows/page. `MLAClient.get_all()` walks
every page automatically using the `"total number rows"` field, so callers always get the
complete result set.

### Rate limit / avoiding a ban

MLA publishes **no numeric rate limit** and returns no rate-limit headers — the docs only
warn that abuse leads to throttling/blacklisting. This client stays well clear by:

- **Sequential only** — never concurrent requests.
- **1s delay between every call** (`REQUEST_DELAY_S`, override with env `MLA_REQUEST_DELAY_S`).
- **Exponential backoff + retry** on HTTP 429/5xx — if throttled it slows down, not hammers.

A full backfill is the only burst (~a few hundred calls over a few minutes, one IP).
Incremental refreshes are tiny. To be extra cautious, run the first backfill off-peak and
set e.g. `MLA_REQUEST_DELAY_S=2`. Don't parallelise calls.

---

## Data refresh details

Refresh reads `MAX(date)` per table and pulls forward from there (re-pulling the last day
to catch revisions). Empty tables cold-start from `BACKFILL_START` in `config.py`
(default `2010-01-01`; the API may return less history — the actual earliest date appears
in the per-report log line).

**Scheduling (Windows Task Scheduler):** create a daily task running
`python -m mla_dashboard.refresh` with **Start in** set to the repo root.

---

## Currency model

Prices are stored in their **native** currency with a `currency` column (AU indicators =
AUD ¢/kg; Steiner global/US = USD). Conversion happens at display time via
`analysis.to_currency()` joined to `fx_rates` by nearest date — never a single spot rate.

---

## Layout

```
src/mla_dashboard/
  config.py      # API base, paths, report registry (single source of truth)
  client.py      # MLAClient — paginated GET, rate-limit, retry
  db.py          # SQLite + Parquet (read falls back to Parquet)
  ingest_mla.py  # fetch -> normalise -> upsert per report
  refresh.py     # incremental/backfill orchestrator (entry point)
  analysis.py    # to_currency(), supply_vs_price(), spreads, YoY
  external/      # fx.py, usda_psd.py, usda_ams.py (90CL/VL), abs.py
app.py                              # Streamlit dashboard
Launch Dashboard.vbs                # no-terminal launcher (Windows)
Refresh Data.vbs                    # no-terminal incremental refresh
Refresh Data (Full Backfill).bat    # first-run full pull
data/parquet/  # committed snapshots the dashboard reads (mla.db is git-ignored)
```

---

## Notes / limits

- `/report/7` global prices are fetched per Steiner country code (USA confirmed; other
  codes probed and skipped if empty).
- ABS dataflow id (`LIVESTOCK_MEAT`) may need updating if ABS re-versions it; the step
  skips gracefully on failure.
- History depth per report is not formally documented — discovered during backfill.
