"""Streamlit dashboard for MLA pricing & supply data.

Reads from the local SQLite/Parquet store populated by ``mla_dashboard.refresh`` — the UI
makes no live API calls. The currency selector (top-left) converts every price chart
between AUD and USD via date-matched FX.

Run:  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mla_dashboard import analysis, db  # noqa: E402

st.set_page_config(page_title="MLA Pricing & Supply", layout="wide")

# Use the full viewport width for charts.
st.markdown(
    """<style>
    .block-container{max-width:98%;padding-top:1.2rem;}
    @media(max-width:640px){
        .block-container{padding-left:0.25rem!important;padding-right:0.25rem!important;}
        .stTabs [data-baseweb="tab"]{padding:0.4rem 0.5rem;font-size:0.8rem;}
    }
    </style>""",
    unsafe_allow_html=True,
)

# Unified hover: hovering anywhere along the x shows a floating box with every series'
# value for that day. Markers make individual points visible/hoverable on the lines.
HOVER = dict(hovermode="x unified")


# Stock-chart style date controls baked into the x-axis: clickable range buttons plus a
# range slider to zoom/pan. "ALL" shows full history.
# Shared pill styling so the range row and the frequency row read as one toolbar.
PILL_BG = "#f0f2f6"
PILL_BORDER = "#888"
PILL_FONT = dict(color="#111", size=12)

RANGE_BUTTONS = dict(
    buttons=[
        dict(count=7, label="7D", step="day", stepmode="backward"),
        dict(count=14, label="14D", step="day", stepmode="backward"),
        dict(count=1, label="1M", step="month", stepmode="backward"),
        dict(count=3, label="3M", step="month", stepmode="backward"),
        dict(count=6, label="6M", step="month", stepmode="backward"),
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(step="all", label="ALL"),
    ],
    bgcolor=PILL_BG, activecolor="#c7d2fe", bordercolor=PILL_BORDER,
    font=PILL_FONT, x=0, y=1.12, xanchor="left", yanchor="bottom",
)


PALETTE = px.colors.qualitative.Plotly

# Max expected spacing per frequency; bigger jumps are real data gaps and the line is
# broken across them instead of drawn as a misleading straight diagonal.
GAP_DAYS = {"Daily": 5, "Weekly": 16, "Monthly": 70, "Yearly": 800}


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


def _style(fig: go.Figure, height: int = 560) -> go.Figure:
    """Range buttons + unified hover for charts that don't use the frequency switcher."""
    fig.update_traces(mode="lines+markers", marker=dict(size=4))
    fig.update_layout(
        height=height, hovermode="x unified", legend_title_text="",
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        margin=dict(b=90),
    )
    fig.update_xaxes(
        type="date", showspikes=True, spikemode="across", spikethickness=1,
        rangeselector=RANGE_BUTTONS, rangeslider=dict(visible=False),
    )
    return fig


def freq_chart(df, date_col, group_col, how, ylabel, height=600, fill=False, default_freq_idx=0):
    """Stock-chart style figure with BOTH controls on the chart:

    - top-left buttons switch Frequency (Daily/Weekly/Monthly/Yearly) by toggling
      pre-resampled traces — no Streamlit rerun.
    - top-right range buttons (7D..ALL) zoom the x-axis. No range slider (no mini graph).
    Prices use mean, volumes use sum (``how``).
    """
    fig = go.Figure()
    freqs = list(analysis.FREQ.keys())
    groups = sorted(df[group_col].dropna().unique())
    color = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(groups)}
    trace_freq = []  # frequency index each trace belongs to
    for fi, fq in enumerate(freqs):
        r = analysis.resample(df, date_col, fq, how, "value", [group_col])
        for g in groups:
            sub = _break_gaps(r[r[group_col] == g], date_col, fq)
            fig.add_trace(go.Scatter(
                x=sub[date_col], y=sub["value"], name=str(g),
                mode="lines+markers", marker=dict(size=4, color=color[g]),
                line=dict(color=color[g]), legendgroup=str(g),
                fill="tozeroy" if fill else None, connectgaps=False,
                visible=(fi == default_freq_idx), showlegend=(fi == default_freq_idx),
            ))
            trace_freq.append(fi)
    buttons = []
    for fi, fq in enumerate(freqs):
        mask = [tf == fi for tf in trace_freq]
        buttons.append(dict(label=fq, method="update", args=[{"visible": mask, "showlegend": mask}]))
    fig.update_layout(
        height=height, hovermode="x unified", legend_title_text="", yaxis_title=ylabel,
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        margin=dict(t=120, b=90),
        updatemenus=[dict(
            type="buttons", direction="right", x=1, y=1.27,
            xanchor="right", yanchor="bottom", showactive=True, active=default_freq_idx,
            bgcolor=PILL_BG, bordercolor=PILL_BORDER, font=PILL_FONT,
            buttons=buttons, pad=dict(t=2, b=2, l=2, r=2),
        )],
    )
    fig.update_xaxes(
        type="date", showspikes=True, spikemode="across", spikethickness=1,
        rangeselector=RANGE_BUTTONS, rangeslider=dict(visible=False),
    )
    return fig


@st.cache_data(ttl=600)
def table(name: str) -> pd.DataFrame:
    return db.read_table(name)


# --- Top bar: title + currency dropdown (top-left, non-intrusive) ---
left, right = st.columns([1, 6])
with left:
    currency = st.selectbox("Currency", ["AUD", "USD"], index=0)
with right:
    st.title("🐂 MLA Pricing & Supply Dashboard")

indicators_ref = table("ref_indicator")
ind_df = table("indicators")
names = (
    indicators_ref.set_index("indicator_id")["indicator_desc"].to_dict()
    if not indicators_ref.empty
    else {i: d for i, d in ind_df[["indicator_id", "indicator_desc"]].drop_duplicates().values}
    if not ind_df.empty
    else {}
)


def ind_label(i: int) -> str:
    return names.get(i, f"Indicator {i}")




prices_tab, supply_tab, svp_tab, global_tab, exports_tab, analysis_tab = st.tabs(
    ["Prices", "Supply", "Supply vs Price", "Global", "Exports", "Analysis"]
)

with prices_tab:
    st.subheader("Australian livestock indicators")
    if ind_df.empty:
        st.info("No indicator data yet. Run `python -m mla_dashboard.refresh --backfill`.")
    else:
        ids = sorted(ind_df["indicator_id"].unique())
        chosen = st.multiselect("Indicators", ids, default=ids[:1], format_func=ind_label)
        frames = [analysis.indicator_series(i, currency) for i in chosen]
        if frames:
            plot = pd.concat(frames)
            plot["label"] = plot["indicator_id"].map(ind_label)
            fig = freq_chart(plot, "calendar_date", "label", analysis.MEAN,
                             f"Price ({currency})")
            st.plotly_chart(fig, width='stretch')
            st.caption("Prices are averaged per period.")

with supply_tab:
    st.subheader("Slaughter & production")
    sp = table("slaughter_production")
    if sp.empty:
        st.info("No supply data yet.")
    else:
        c1, c2, c3 = st.columns(3)
        rtype = c1.selectbox("Report type", sorted(sp["report_type"].dropna().unique()))
        loc = c2.selectbox("Location", sorted(sp["location_id"].dropna().unique()),
                           index=0)
        cats = sorted(sp["category"].dropna().unique())
        chosen_cats = c3.multiselect("Categories", cats, default=cats[:3])
        sub = sp[(sp["report_type"] == rtype) & (sp["location_id"] == loc)
                 & (sp["category"].isin(chosen_cats))]
        if sub.empty:
            st.info("No rows for that selection.")
        else:
            fig = freq_chart(sub, "report_date", "category", analysis.SUM, "Volume")
            st.plotly_chart(fig, width='stretch')
            st.caption("Volumes are summed per period.")

with svp_tab:
    st.subheader("Supply vs price — by species")
    sp = table("slaughter_production")
    if ind_df.empty or sp.empty:
        st.info("Need both indicator and slaughter/production data. Run a backfill.")
    else:
        c1, c2, c3 = st.columns(3)
        species = c1.selectbox("Species", list(analysis.SPECIES_MAP.keys()))
        ind_opts = analysis.indicators_for_species(species)
        ind_id = c2.selectbox(
            "Price indicator",
            ind_opts["indicator_id"].tolist(),
            format_func=ind_label,
        )
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
            fig.add_trace(
                go.Scatter(x=data["month"], y=data["price"], name=f"Price ({currency})",
                           mode="lines+markers"), secondary_y=False)
            fig.add_trace(
                go.Bar(x=data["month"], y=data["volume"],
                       name=f"{rtype} ({unit})", opacity=0.45), secondary_y=True)
            fig.update_layout(height=580, hovermode="x unified", legend_title_text="",
                              bargap=0.1)
            fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
            fig.update_yaxes(title_text=f"Price ({currency})", secondary_y=False)
            fig.update_yaxes(title_text=f"{rtype} volume ({unit})", secondary_y=True)
            st.plotly_chart(fig, width='stretch')
            corr = data["price"].corr(data["volume"])
            st.metric(f"{species} price–{rtype.lower()} correlation", f"{corr:.2f}")

with global_tab:
    st.subheader(f"AU vs global cattle prices ({currency})")
    gl = table("global_cattle_prices")
    if gl.empty:
        st.info("No global price data yet.")
    else:
        glc = analysis.to_currency(gl, currency, "indicator_date")
        fig = freq_chart(glc, "indicator_date", "indicator_desc", analysis.MEAN,
                         f"Price ({currency})")
        st.plotly_chart(fig, width='stretch')

with exports_tab:
    st.subheader("Australian red meat exports")
    ex = table("exports")
    if ex.empty:
        st.info("No export data yet.")
    else:
        top = ex.groupby("country")["value"].sum().nlargest(10).index
        sub = ex[ex["country"].isin(top)]
        fig = freq_chart(sub, "result_date", "country", analysis.SUM, "Weight", fill=True, default_freq_idx=2)
        st.plotly_chart(fig, width='stretch')

with analysis_tab:
    st.subheader("AU vs global spread & correlation")
    if ind_df.empty:
        st.info("No data yet.")
    else:
        ids = sorted(ind_df["indicator_id"].unique())
        ind = st.selectbox("AU indicator", ids, format_func=ind_label, key="spread_ind")
        spread = analysis.au_vs_global_spread(ind, currency)
        if spread.empty:
            st.info("Need both AU indicator and global price data for the spread.")
        else:
            fig = px.line(spread, x="month", y=["au", "global", "spread"],
                          labels={"value": f"Price ({currency})"})
            st.plotly_chart(_style(fig), width='stretch')
            corr = spread[["au", "global"]].corr().iloc[0, 1]
            st.metric("AU–global price correlation", f"{corr:.2f}")
