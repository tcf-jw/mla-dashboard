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

from mla_dashboard import analysis, db  # noqa: E402

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
GAP_DAYS = {"Daily": 5, "Weekly": 16, "Monthly": 70, "Yearly": 800}


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


def freq_radio(key: str, default: str = "Weekly") -> str:
    """Native, touch-friendly frequency switcher shown above a chart.

    Replaces the old on-chart Plotly buttons, which overlapped the range buttons and were
    too small to tap on a phone. Reruns on change; cached reads keep it snappy.
    """
    opts = list(analysis.FREQ.keys())
    return st.radio(
        "Frequency", opts, index=opts.index(default), horizontal=True,
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


prices_tab, supply_tab, svp_tab, global_tab, exports_tab, lean_tab, analysis_tab = st.tabs(
    ["Prices", "Supply", "Supply/Price", "Global", "Exports", "90CL/VL", "Analysis"]
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

            freq = freq_radio("prices_freq", "Daily")
            plot = pd.concat(frames)
            plot["label"] = plot["indicator_id"].map(ind_label)
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
            freq = freq_radio("supply_freq", "Monthly")
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
        freq = freq_radio("global_freq", "Weekly")
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
        freq = freq_radio("exports_freq", "Monthly")
        fig = series_chart(sub, "result_date", "country", analysis.SUM, "Weight", freq,
                           fill=True, si=True)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Top {n} destinations by total volume over the period.")
        download(sub[["result_date", "country", "value"]], "exports.csv")

with lean_tab:
    st.subheader(f"US lean / trim beef — 90CL & VL grades ({currency})")
    lb = table("lean_beef_prices")
    if lb.empty:
        no_data("No 90CL/VL data yet.")
        st.caption("Set `USDA_AMS_API_KEY` (free key from mymarketnews.ams.usda.gov), then "
                   "run a refresh to pull USDA AMS lean/trim beef prices — the reference "
                   "for Australian export grinding beef.")
    else:
        series_opt = sorted(lb["series"].dropna().unique())
        ser = st.selectbox("Report", series_opt)
        sub = lb[lb["series"] == ser]
        sub = analysis.to_currency(sub, currency, "result_date")
        freq = freq_radio("lean_freq", "Weekly")
        fig = series_chart(sub, "result_date", "grade", analysis.MEAN,
                           f"Price ({currency}/cwt)", freq)
        st.plotly_chart(fig, width="stretch")
        st.caption("Chemical-lean (CL) / visual-lean (VL) grades, e.g. 90CL grinding beef. "
                   "USDA AMS negotiated sales.")
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
