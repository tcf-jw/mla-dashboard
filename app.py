"""Streamlit dashboard for MLA pricing & supply data.

Reads from the local SQLite/Parquet store populated by ``mla_dashboard.refresh`` — the UI
makes no live API calls. The currency selector (sidebar) converts every price chart
between AUD and USD via date-matched FX.

Run:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mla_dashboard import analysis, db, leadlag  # noqa: E402

st.set_page_config(page_title="MLA Pricing & Supply", layout="wide", page_icon="🐂")

# Responsive layout: roomy on desktop, edge-to-edge with smaller chrome on phones.
st.markdown(
    """<style>
    .block-container{max-width:1500px;padding-top:1rem;}
    /* Make the horizontal frequency radio read as a compact pill toolbar. */
    div[role="radiogroup"]{gap:0.25rem;}
    @media(max-width:640px){
        .block-container{padding-left:0.4rem!important;padding-right:0.4rem!important;}
        h1{font-size:1.5rem!important;}
        .stTabs [data-baseweb="tab"]{padding:0.35rem 0.5rem;font-size:0.78rem;}
    }
    </style>""",
    unsafe_allow_html=True,
)

# Shared pill styling for the on-chart range selector.
PILL_BG = "#f0f2f6"
PILL_BORDER = "#888"
PILL_FONT = dict(color="#111", size=13)
PALETTE = px.colors.qualitative.Plotly

# Trimmed to five ranges so the row never overflows a phone; daily detail is still
# reachable by pinch-zoom. Frequency (Daily/Weekly/…) is a native control above the chart.
RANGE_BUTTONS = dict(
    buttons=[
        dict(count=1, label="1M", step="month", stepmode="backward"),
        dict(count=3, label="3M", step="month", stepmode="backward"),
        dict(count=6, label="6M", step="month", stepmode="backward"),
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(step="all", label="ALL"),
    ],
    bgcolor=PILL_BG, activecolor="#c7d2fe", bordercolor=PILL_BORDER,
    borderwidth=1, font=PILL_FONT, x=0, y=1.0, xanchor="left", yanchor="bottom",
)

CHART_H = 460  # fits a phone screen with the legend below; comfortable on desktop too.

# Max expected spacing per frequency; bigger jumps are real data gaps and the line is
# broken across them instead of drawn as a misleading straight diagonal.
GAP_DAYS = {"Daily": 5, "Weekly": 16, "Monthly": 70, "Quarterly": 210, "Yearly": 800}


def color_for(label) -> str:
    """Deterministic colour per label so a series keeps its colour across every tab."""
    h = int(hashlib.md5(str(label).encode()).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


def _break_gaps(sub, date_col, freq_label):
    """Insert a NaN row across any gap larger than expected so the line breaks there."""
    sub = sub.copy()
    sub[date_col] = pd.to_datetime(sub[date_col])
    sub = sub.sort_values(date_col).reset_index(drop=True)
    if len(sub) < 2:
        return sub
    thr = pd.Timedelta(days=GAP_DAYS[freq_label])
    big = sub[date_col].diff() > thr
    if not big.any():
        return sub
    rows = []
    for i in range(len(sub)):
        if big.iloc[i]:
            mid = sub[date_col].iloc[i - 1] + (sub[date_col].iloc[i] - sub[date_col].iloc[i - 1]) / 2
            rows.append({date_col: mid, "value": None})
        rows.append(sub.iloc[i].to_dict())
    return pd.DataFrame(rows)


def freq_radio(key: str, df, date_col: str, group_cols=None) -> str:
    """Native, touch-friendly frequency switcher shown above a chart.

    Options are derived from the data: only the chart's native cadence and coarser are
    offered (a monthly series won't offer Daily/Weekly), and the default is the native
    cadence. This avoids resampling to a granularity the data never had — which would only
    invent empty periods. Reruns on change; cached reads keep it snappy.

    Replaces the old on-chart Plotly buttons, which overlapped the range buttons and were
    too small to tap on a phone.
    """
    if isinstance(group_cols, str):
        group_cols = [group_cols]
    opts = analysis.freq_options(df, date_col, group_cols)
    return st.radio(
        "Frequency", opts, index=0, horizontal=True,
        key=key, label_visibility="collapsed",
    )


def series_chart(df, date_col, group_col, how, ylabel, freq,
                 fill=False, height=CHART_H, si=False) -> go.Figure:
    """Multi-series line chart for one frequency: range buttons, unified hover,
    horizontal legend below, gap-aware lines and stable per-label colours.

    ``si`` formats the y-axis/hover with SI suffixes (1.9M instead of 1900000) for volumes.
    """
    fig = go.Figure()
    groups = sorted(df[group_col].dropna().unique())
    r = analysis.resample(df, date_col, freq, how, "value", [group_col])
    for g in groups:
        sub = _break_gaps(r[r[group_col] == g], date_col, freq)
        fig.add_trace(go.Scatter(
            x=sub[date_col], y=sub["value"], name=str(g),
            mode="lines+markers", marker=dict(size=4, color=color_for(g)),
            line=dict(color=color_for(g)), legendgroup=str(g),
            fill="tozeroy" if fill else None, connectgaps=False,
        ))
    fig.update_layout(
        height=height, hovermode="x unified", legend_title_text="", yaxis_title=ylabel,
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        margin=dict(t=28, b=80, l=10, r=10), font=dict(size=13),
    )
    fig.update_xaxes(
        type="date", showspikes=True, spikemode="across", spikethickness=1,
        rangeselector=RANGE_BUTTONS, rangeslider=dict(visible=False),
    )
    if si:
        fig.update_yaxes(tickformat="~s", hoverformat="~s")
    return fig


def _style(fig: go.Figure, height: int = CHART_H) -> go.Figure:
    """Range buttons + unified hover + horizontal legend for hand-built figures."""
    fig.update_layout(
        height=height, hovermode="x unified", legend_title_text="", font=dict(size=13),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        margin=dict(t=28, b=80, l=10, r=10),
    )
    fig.update_xaxes(
        type="date", showspikes=True, spikemode="across", spikethickness=1,
        rangeselector=RANGE_BUTTONS, rangeslider=dict(visible=False),
    )
    return fig


def download(df: pd.DataFrame, fname: str) -> None:
    """Consistent CSV export under each chart."""
    st.download_button(
        "⬇ Download CSV", df.to_csv(index=False).encode(), fname, "text/csv",
        key=f"dl_{fname}",
    )


def no_data(msg: str = "No data yet.") -> None:
    """Standardised empty state that always tells the user how to populate it."""
    st.info(f"{msg}  Run `python -m mla_dashboard.refresh --backfill` to populate.")


@st.cache_data(ttl=600)
def table(name: str) -> pd.DataFrame:
    return db.read_table(name)


def freshness(name: str, date_col: str) -> str | None:
    """Latest date held for a table (works off the Parquet fallback too)."""
    df = table(name)
    if df.empty or date_col not in df.columns:
        return None
    return str(pd.to_datetime(df[date_col], errors="coerce").max().date())


# --- Sidebar: global controls + data freshness -----------------------------------------
with st.sidebar:
    st.header("Settings")
    currency = st.radio(
        "Currency", ["AUD", "USD"], index=0,
        help="Converts every price chart between AUD and USD using date-matched FX "
             "(a 2023 price uses the 2023 rate, not today's spot).",
    )
    st.divider()
    st.markdown("**Data freshness**")
    _fresh = {
        "Prices": ("indicators", "calendar_date"),
        "Supply": ("slaughter_production", "report_date"),
        "Exports": ("exports", "result_date"),
        "Global": ("global_cattle_prices", "indicator_date"),
        "90CL/VL": ("lean_beef_prices", "result_date"),
    }
    for label, (t, c) in _fresh.items():
        st.caption(f"{label}: {freshness(t, c) or '—'}")
    st.caption("Refresh with `python -m mla_dashboard.refresh`.")

# --- Header ----------------------------------------------------------------------------
st.title("🐂 MLA Pricing & Supply Dashboard")
_latest = [d for d in (freshness("indicators", "calendar_date"),
                       freshness("exports", "result_date")) if d]
if _latest:
    st.caption(f"Prices to {freshness('indicators', 'calendar_date') or '—'} · "
               f"Exports to {freshness('exports', 'result_date') or '—'} · "
               f"Currency: {currency}")

indicators_ref = table("ref_indicator")
ind_df = table("indicators")
names = (
    indicators_ref.drop_duplicates("indicator_id").set_index("indicator_id")["indicator_desc"].to_dict()
    if not indicators_ref.empty
    else {i: d for i, d in ind_df[["indicator_id", "indicator_desc"]].drop_duplicates().values}
    if not ind_df.empty
    else {}
)


def ind_label(i: int) -> str:
    return names.get(i, f"Indicator {i}")


def default_indicator(ids: list[int]) -> int:
    """Land on EYCI (the headline cattle benchmark) if present, else the first id."""
    for iid in ids:
        if "eastern young cattle" in ind_label(iid).lower():
            return iid
    return ids[0]


(prices_tab, supply_tab, svp_tab, global_tab, exports_tab, lean_tab, analysis_tab,
 leadlag_tab) = st.tabs(
    ["Prices", "Supply", "Supply/Price", "Global", "Exports", "90CL/VL", "Analysis",
     "Lead/Lag"]
)

with prices_tab:
    st.subheader("Australian livestock indicators")
    if ind_df.empty:
        no_data("No indicator data yet.")
    else:
        ids = sorted(ind_df["indicator_id"].unique())
        chosen = st.multiselect(
            "Indicators", ids, default=[default_indicator(ids)], format_func=ind_label,
            help="Saleyard price indicators (cents/kg). EYCI is the headline cattle benchmark.",
        )
        frames = [analysis.indicator_series(i, currency) for i in chosen]
        frames = [f for f in frames if not f.empty]
        if frames:
            # Latest value + 1-month change for each selected indicator (key numbers up top).
            cols = st.columns(min(len(frames), 4))
            for col, fr in zip(cols, frames[:4]):
                s = fr.sort_values("calendar_date")
                latest = s["value"].iloc[-1]
                prev = s["value"].iloc[-22] if len(s) > 22 else s["value"].iloc[0]
                delta = (latest - prev) / prev * 100 if prev else 0
                col.metric(ind_label(int(s["indicator_id"].iloc[0]))[:22],
                           f"{latest:,.0f}", f"{delta:+.1f}% (1m)")

            plot = pd.concat(frames)
            plot["label"] = plot["indicator_id"].map(ind_label)
            freq = freq_radio("prices_freq", plot, "calendar_date", "label")
            fig = series_chart(plot, "calendar_date", "label", analysis.MEAN, f"Price ({currency})", freq)
            st.plotly_chart(fig, width="stretch")
            st.caption("Prices are averaged per period. Tap a legend item to toggle a series.")
            download(plot[["calendar_date", "label", "value"]], "prices.csv")

with supply_tab:
    st.subheader("Slaughter & production")
    sp = table("slaughter_production")
    if sp.empty:
        no_data("No supply data yet.")
    else:
        c1, c2 = st.columns(2)
        rtype = c1.selectbox("Report type", sorted(sp["report_type"].dropna().unique()))
        loc = c2.selectbox("Location", sorted(sp["location_id"].dropna().unique()), index=0)
        cats = sorted(sp["category"].dropna().unique())
        chosen_cats = st.multiselect("Categories", cats, default=cats[:3])
        sub = sp[(sp["report_type"] == rtype) & (sp["location_id"] == loc)
                 & (sp["category"].isin(chosen_cats))]
        if sub.empty:
            st.info("No rows for that selection.")
        else:
            unit = sub["unit"].dropna().iloc[0] if sub["unit"].notna().any() else ""
            freq = freq_radio("supply_freq", sub, "report_date", "category")
            fig = series_chart(sub, "report_date", "category", analysis.SUM,
                               f"Volume ({unit})" if unit else "Volume", freq, si=True)
            st.plotly_chart(fig, width="stretch")
            st.caption("Volumes are summed per period.")
            download(sub[["report_date", "category", "value"]], "supply.csv")

with svp_tab:
    st.subheader("Supply vs price — by species")
    sp = table("slaughter_production")
    if ind_df.empty or sp.empty:
        no_data("Need both indicator and slaughter/production data.")
    else:
        c1, c2, c3 = st.columns(3)
        species = c1.selectbox("Species", list(analysis.SPECIES_MAP.keys()))
        ind_opts = analysis.indicators_for_species(species)
        ind_id = c2.selectbox("Price indicator", ind_opts["indicator_id"].tolist(), format_func=ind_label)
        valid_cats = [c for c in analysis.SPECIES_MAP[species]["categories"]
                      if c in set(sp["category"])]
        category = c3.selectbox("Supply category", valid_cats)
        rtype = st.radio("Measure", ["Slaughter", "Production"], horizontal=True)

        data = analysis.supply_vs_price(ind_id, category, currency, rtype)
        if data.empty:
            st.info("No overlapping months for that combination.")
        else:
            unit = data["unit"].iloc[0]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=data["month"], y=data["price"], name=f"Price ({currency})",
                                     mode="lines+markers", line=dict(color=color_for("price"))),
                          secondary_y=False)
            fig.add_trace(go.Bar(x=data["month"], y=data["volume"], name=f"{rtype} ({unit})",
                                 opacity=0.45, marker_color=color_for(rtype)), secondary_y=True)
            fig.update_yaxes(title_text=f"Price ({currency})", secondary_y=False)
            fig.update_yaxes(title_text=f"{rtype} ({unit})", tickformat="~s", secondary_y=True)
            fig.update_xaxes(title_text="Month")
            st.plotly_chart(_style(fig), width="stretch")
            corr = data["price"].corr(data["volume"])
            st.metric(f"{species} price–{rtype.lower()} correlation", f"{corr:.2f}")
            st.caption(f"Monthly aggregation · Pearson r over {len(data)} months.")
            download(data, "supply_vs_price.csv")

with global_tab:
    st.subheader(f"AU vs global cattle prices ({currency})")
    gl = table("global_cattle_prices")
    if gl.empty:
        no_data("No global price data yet.")
    else:
        glc = analysis.to_currency(gl, currency, "indicator_date")
        freq = freq_radio("global_freq", glc, "indicator_date", "indicator_desc")
        fig = series_chart(glc, "indicator_date", "indicator_desc", analysis.MEAN,
                           f"Price ({currency})", freq)
        st.plotly_chart(fig, width="stretch")
        download(glc[["indicator_date", "indicator_desc", "value"]], "global_prices.csv")

with exports_tab:
    st.subheader("Australian red meat exports")
    ex = table("exports")
    if ex.empty:
        no_data("No export data yet.")
    else:
        n = st.slider("Top destinations", 3, 12, 8)
        top = ex.groupby("country")["value"].sum().nlargest(n).index
        sub = ex[ex["country"].isin(top)]
        freq = freq_radio("exports_freq", sub, "result_date", "country")
        fig = series_chart(sub, "result_date", "country", analysis.SUM, "Weight", freq,
                           fill=True, si=True)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Top {n} destinations by total volume over the period.")
        download(sub[["result_date", "country", "value"]], "exports.csv")

with lean_tab:
    st.subheader(f"Lean / trim beef — 90CL & VL grades ({currency})")
    lb = table("lean_beef_prices")
    if lb.empty:
        no_data("No 90CL/VL data yet.")
        st.caption("Import MLA's indicative imported 90CL series with "
                   "`python -m mla_dashboard.external.mla_90cl_manual`, and/or set "
                   "`USDA_AMS_API_KEY` (free key from mymarketnews.ams.usda.gov) and run a "
                   "refresh to pull USDA AMS US negotiated lean/trim beef prices.")
    else:
        series_opt = sorted(lb["series"].dropna().unique())
        ser = st.selectbox("Report", series_opt)
        sub = lb[lb["series"] == ser]
        sub = analysis.to_currency(sub, currency, "result_date")
        # Weight basis varies by source (MLA c/kg, Steiner c/lb, AMS $/cwt), so normalise
        # to per-kg: otherwise the same 90CL price reads three different ways.
        sub, basis = analysis.to_per_kg(sub)
        ylabel = f"Price ({currency} · {basis})" if basis else f"Price ({currency})"
        freq = freq_radio("lean_freq", sub, "result_date", "grade")
        fig = series_chart(sub, "result_date", "grade", analysis.MEAN, ylabel, freq)
        st.plotly_chart(fig, width="stretch")
        st.caption("Chemical-lean (CL) / visual-lean (VL) grades, e.g. 90CL grinding beef. "
                   "MLA imported 90CL is the AU CIF import-parity price (c/kg, manual "
                   "export); US imported (Steiner) is MLA report 9, quoted US c/lb and "
                   "refreshed daily; USDA AMS series are US negotiated sales ($/cwt). "
                   "All are normalised to a per-kg basis for comparison.")
        download(sub[["result_date", "grade", "value"]], "lean_beef.csv")

with analysis_tab:
    st.subheader("AU vs global spread & correlation")
    if ind_df.empty:
        no_data("No data yet.")
    else:
        ids = sorted(ind_df["indicator_id"].unique())
        ind = st.selectbox("AU indicator", ids, index=ids.index(default_indicator(ids)),
                           format_func=ind_label, key="spread_ind")
        spread = analysis.au_vs_global_spread(ind, currency)
        if spread.empty:
            st.info("Need both AU indicator and global price data for the spread.")
        else:
            fig = px.line(spread, x="month", y=["au", "global", "spread"],
                          labels={"value": f"Price ({currency})", "month": "Month",
                                  "variable": ""},
                          color_discrete_sequence=[color_for("au"), color_for("global"),
                                                   color_for("spread")])
            fig.update_traces(mode="lines+markers", marker=dict(size=4))
            st.plotly_chart(_style(fig), width="stretch")
            corr = spread[["au", "global"]].corr().iloc[0, 1]
            st.metric("AU–global price correlation", f"{corr:.2f}")
            st.caption(f"Monthly aggregation · Pearson r over {len(spread)} months.")
            download(spread, "au_vs_global.csv")


# --- Lead/Lag ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def _catalogue() -> list[dict]:
    return leadlag.catalogue()


@st.cache_data(ttl=600)
def _matrix(keys: tuple[str, ...], freq: str, cur: str) -> pd.DataFrame:
    """Resampled wide frame for the chosen keys.

    Cached on the keys rather than the specs: the spec dicts are unhashable, and the keys
    identify them uniquely anyway.
    """
    by_key = {c["key"]: c for c in _catalogue()}
    return leadlag.matrix([by_key[k] for k in keys if k in by_key], freq, cur)


def _lag_key(key: str) -> str:
    return f"lag_{key}"


with leadlag_tab:
    st.subheader("Lead/lag & correlation")
    cat = _catalogue()
    if not cat:
        no_data("No series available.")
    else:
        label_of = {c["key"]: f"{c['group']} · {c['label']}" for c in cat}
        keys = list(label_of)

        def _find(fragment: str, fallback: str) -> str:
            hit = next((k for k in keys if fragment.lower() in label_of[k].lower()), None)
            return hit or fallback

        c1, c2 = st.columns([1, 2])
        with c1:
            ref = st.selectbox(
                "Reference series", keys,
                index=keys.index(_find("Eastern Young Cattle", keys[0])),
                format_func=lambda k: label_of[k], key="ll_ref",
                help="Every other series is measured against this one.",
            )
        with c2:
            default_cmp = [k for k in (_find("90CL Boneless Beef, NZ/Australia", ""),
                                       _find("AUD/USD", "")) if k and k != ref]
            compare = st.multiselect(
                "Compare against", [k for k in keys if k != ref], default=default_cmp,
                format_func=lambda k: label_of[k], key="ll_cmp",
            )

        c3, c4, c5 = st.columns(3)
        freq = c3.radio(
            "Frequency", list(leadlag.FREQ_RULES), index=1, horizontal=True, key="ll_freq",
            help="Series are resampled onto this calendar before aligning: prices "
                 "averaged, volumes summed.",
        )
        max_lag = c4.number_input("Max lag to scan (periods)", 1, 104, 12, key="ll_maxlag")
        scale = c5.radio("Overlay scale", ["Index = 100", "Z-score"], horizontal=True,
                         key="ll_scale")

        if not compare:
            st.info("Pick at least one series to compare against the reference.")
        else:
            wide = _matrix(tuple([ref] + compare), freq, currency)
            if wide.empty or ref not in wide.columns:
                st.info("No overlapping data for that combination.")
            else:
                # Applied here, before the lag widgets exist: Streamlit refuses to write a
                # widget's session state once that widget has been instantiated this run,
                # so the button below only raises a flag and reruns.
                if st.session_state.pop("ll_apply_best", False):
                    for k, v in leadlag.best_lags(wide, ref, int(max_lag)).items():
                        st.session_state[_lag_key(k)] = int(v)

                st.markdown("**Lag per series** (periods; positive = leads the reference)")
                lag_cols = st.columns(min(len(compare), 4))
                lags = {}
                for i, k in enumerate(compare):
                    if k not in wide.columns:
                        continue
                    # Explicit 0 default: without it the widget starts at its minimum,
                    # silently lagging every series by the full scan range.
                    lags[k] = lag_cols[i % len(lag_cols)].number_input(
                        label_of[k], -int(max_lag), int(max_lag), 0, key=_lag_key(k),
                    )

                if st.button("Suggest best lags", key="ll_suggest",
                             help="Scans every lag in range and picks the one maximising "
                                  "|r| on percentage change."):
                    st.session_state["ll_apply_best"] = True
                    st.rerun()

                lagged = leadlag.apply_lags(wide, lags)

                plot = leadlag.rebase(lagged, "zscore" if scale == "Z-score" else "index")
                fig = go.Figure()
                for k in plot.columns:
                    s = plot[k].dropna()
                    # The reference takes the neutral ink colour from the design tokens so
                    # it always reads as the anchor, whatever the compared series get.
                    is_ref = k == ref
                    fig.add_trace(go.Scatter(
                        x=s.index, y=s.values, name=label_of.get(k, k), mode="lines",
                        line=dict(color="#171717" if is_ref else color_for(k),
                                  width=3 if is_ref else 2),
                    ))
                unit = "Z-score" if scale == "Z-score" else "Index (first period = 100)"
                fig.update_layout(yaxis_title=unit)
                st.plotly_chart(_style(fig), width="stretch")
                st.caption(
                    f"{freq} aggregation, lags applied, reference drawn thicker. Series are "
                    "rescaled to share one axis, so read shape, not level."
                )

                mt = leadlag.metrics(lagged, ref)
                if mt.empty:
                    st.info("Not enough overlapping observations to correlate.")
                else:
                    show = mt.assign(series=mt["series"].map(lambda k: label_of.get(k, k)))
                    show = show.rename(columns={
                        "n": "Obs", "pearson_levels": "Pearson (levels)",
                        "spearman_levels": "Spearman (levels)",
                        "pearson_returns": "Pearson (% change)",
                        "spearman_returns": "Spearman (% change)",
                        "trend_driven": "Trend-driven?",
                    })
                    st.dataframe(show.set_index("series"), width="stretch")
                    if mt["trend_driven"].any():
                        st.warning(
                            "Flagged rows correlate far better on levels than on percentage "
                            "change. That is two series sharing a trend, not one moving with "
                            "the other. Trust the percentage-change column."
                        )
                    download(mt, "leadlag_metrics.csv")

                st.divider()
                focus = st.selectbox("Detail for", compare,
                                     format_func=lambda k: label_of[k], key="ll_focus")
                d1, d2 = st.columns(2)
                with d1:
                    cc = leadlag.cross_correlation(wide, ref, focus, int(max_lag))
                    ccf = go.Figure(go.Bar(x=cc["lag"], y=cc["r"],
                                           marker_color=color_for(focus)))
                    ccf.update_layout(height=320, xaxis_title="Lag (periods, + = leads)",
                                      yaxis_title="Pearson r (% change)",
                                      margin=dict(t=30, b=40, l=10, r=10))
                    st.plotly_chart(ccf, width="stretch")
                    peak = cc.dropna(subset=["r"])
                    if not peak.empty:
                        row = peak.loc[peak["r"].abs().idxmax()]
                        st.caption(f"Strongest at lag {int(row['lag'])}: r = {row['r']:.3f} "
                                   f"over {int(row['n'])} periods.")
                with d2:
                    win = st.slider("Rolling window (periods)", 6, 60, 24, key="ll_win")
                    roll = leadlag.rolling_correlation(lagged, ref, focus, int(win))
                    if roll.empty:
                        st.info("Not enough history for that window.")
                    else:
                        rf = go.Figure(go.Scatter(x=roll["date"], y=roll["r"], mode="lines",
                                                  line=dict(color=color_for(focus))))
                        rf.update_layout(height=320, yaxis_title="Rolling r (% change)",
                                         margin=dict(t=30, b=40, l=10, r=10))
                        rf.update_yaxes(range=[-1, 1])
                        st.plotly_chart(rf, width="stretch")
                        st.caption("A relationship that decays shows here as a drift toward 0.")

                download(lagged.reset_index(names="date"), "leadlag_series.csv")
