"""Lead/lag workbench: align any stored series, shift them, and measure co-movement.

Every table in the store is exposed as a flat catalogue of pickable series. Because those
tables run from daily (indicators, FX) to quarterly (CPI, ABS), nothing can be correlated
until it is resampled onto one shared calendar, so the caller chooses a frequency and each
series is aggregated onto it: prices by mean, volumes by sum.

Lag convention: a lag of ``k`` periods shifts a series **forward** by k, so its value at
``t - k`` is lined up against the reference at ``t``. Positive k therefore means "this
series leads the reference by k periods" and is the sign you want when hunting for an
early indicator.

Correlations are reported on both levels and period-over-period percentage change. Levels
correlation between two trending price series is close to meaningless (both trend up, so r
approaches 1 regardless of any real relationship); the percentage-change figure is the
honest one. ``metrics`` flags the gap between them rather than leaving the reader to spot
it, see ``SPURIOUS_GAP``.
"""

from __future__ import annotations

import pandas as pd

from . import analysis, db

# Resample rules per label. Period-end stamps keep quarterly CPI aligned with the
# period-end dates already stored for CPI and ABS.
FREQ_RULES = {"Weekly": "W", "Monthly": "ME", "Quarterly": "QE"}

# Levels r this much above returns r means the pair mostly shares a trend, not a
# relationship. Judgement call, not a statistical threshold: 0.3 is wide enough that
# genuinely co-moving series do not trip it.
SPURIOUS_GAP = 0.3

PRICE = "mean"
VOLUME = "sum"


def _spec(key, label, group, table, date_col, value_col, agg, filters=None, currency=None):
    return {
        "key": key, "label": label, "group": group, "table": table,
        "date_col": date_col, "value_col": value_col, "agg": agg,
        "filters": filters or {}, "currency": currency,
    }


def _catalogue_indicators(out: list) -> None:
    df = db.read_table("indicators")
    if df.empty:
        return
    for iid, desc in df[["indicator_id", "indicator_desc"]].drop_duplicates().values:
        out.append(_spec(
            f"ind:{iid}", str(desc), "AU indicators", "indicators",
            "calendar_date", "value", PRICE, {"indicator_id": iid}, "AUD",
        ))


def _catalogue_lean(out: list) -> None:
    df = db.read_table("lean_beef_prices")
    if df.empty:
        return
    for series, grade in df[["series", "grade"]].drop_duplicates().values:
        out.append(_spec(
            f"lean:{series}|{grade}", f"{grade} ({series})", "Lean / trim beef",
            "lean_beef_prices", "result_date", "value", PRICE,
            {"series": series, "grade": grade}, None,
        ))


def _catalogue_global(out: list) -> None:
    df = db.read_table("global_cattle_prices")
    if df.empty:
        return
    for cc, desc in df[["country_code", "indicator_desc"]].drop_duplicates().values:
        out.append(_spec(
            f"glob:{cc}|{desc}", f"{cc}: {desc}", "Global prices", "global_cattle_prices",
            "indicator_date", "value", PRICE, {"country_code": cc, "indicator_desc": desc},
            "USD",
        ))


def _catalogue_fx(out: list) -> None:
    if db.read_table("fx_rates").empty:
        return
    # FX is a rate, not a price: never currency-converted, or the toggle would square it.
    out.append(_spec("fx:aud_usd", "AUD/USD", "FX", "fx_rates", "date", "aud_usd", PRICE))


def _catalogue_cpi(out: list) -> None:
    df = db.read_table("cpi")
    if df.empty:
        return
    labels = {"Index numbers": "CPI", "Percentage change from previous year": "CPI YoY"}
    for measure, prefix in labels.items():
        cats = df[df["measure"] == measure]["category"].dropna().unique()
        for cat in sorted(cats):
            out.append(_spec(
                f"cpi:{measure}|{cat}", f"{prefix}: {cat}", "CPI", "cpi",
                "period_end", "value", PRICE, {"measure": measure, "category": cat},
            ))


def _catalogue_volumes(out: list) -> None:
    ex = db.read_table("exports")
    if not ex.empty:
        for mt in sorted(ex["meat_type"].dropna().unique()):
            out.append(_spec(
                f"exp:{mt}", f"Exports: {mt} (all destinations)", "Exports", "exports",
                "result_date", "value", VOLUME, {"meat_type": mt},
            ))
        # Only the biggest destinations: the tail is noise at a country level.
        top = (ex.groupby("country")["value"].sum().nlargest(10).index)
        for country in top:
            for mt in sorted(ex[ex["country"] == country]["meat_type"].dropna().unique()):
                out.append(_spec(
                    f"exp:{country}|{mt}", f"Exports: {mt} to {country}", "Exports",
                    "exports", "result_date", "value", VOLUME,
                    {"country": country, "meat_type": mt},
                ))

    sp = db.read_table("slaughter_production")
    if not sp.empty:
        for rt, cat in sp[["report_type", "category"]].drop_duplicates().values:
            out.append(_spec(
                f"sp:{rt}|{cat}", f"{rt}: {cat}", "Slaughter & production",
                "slaughter_production", "report_date", "value", VOLUME,
                {"report_type": rt, "category": cat},
            ))

    nl = db.read_table("nlrs_slaughter")
    if not nl.empty:
        for sp_id in sorted(nl["species_id"].dropna().unique()):
            out.append(_spec(
                f"nlrs:{sp_id}", f"NLRS slaughter: {sp_id}", "Slaughter & production",
                "nlrs_slaughter", "result_date", "value", VOLUME, {"species_id": sp_id},
            ))

    yd = db.read_table("yardings")
    if not yd.empty:
        for cat in sorted(yd["category"].dropna().unique()):
            out.append(_spec(
                f"yard:{cat}", f"Yardings: {cat}", "Slaughter & production", "yardings",
                "result_date", "value", VOLUME, {"category": cat},
            ))

    ab = db.read_table("ext_abs_slaughter")
    if not ab.empty:
        au = ab[ab["state"] == "Australia"]
        for ds, cat in au[["dataset", "category"]].drop_duplicates().values:
            out.append(_spec(
                f"abs:{ds}|{cat}", f"ABS {ds}: {cat}", "ABS (quarterly)",
                "ext_abs_slaughter", "period_end", "value", VOLUME,
                {"dataset": ds, "category": cat, "state": "Australia"},
            ))


def catalogue() -> list[dict]:
    """Every series in the store that can be plotted on a shared time axis."""
    out: list[dict] = []
    for fn in (_catalogue_indicators, _catalogue_lean, _catalogue_global,
               _catalogue_fx, _catalogue_cpi, _catalogue_volumes):
        fn(out)
    return out


def load(spec: dict, currency: str = "AUD") -> pd.Series:
    """One series as a date-indexed Series, currency-converted where that means anything."""
    df = db.read_table(spec["table"])
    if df.empty:
        return pd.Series(dtype=float)
    for col, val in spec["filters"].items():
        if col not in df.columns:
            return pd.Series(dtype=float)
        df = df[df[col] == val]
    if df.empty:
        return pd.Series(dtype=float)

    date_col, value_col = spec["date_col"], spec["value_col"]
    if value_col != "value" and value_col in df.columns:
        df = df.rename(columns={value_col: "value"})
    # A stored currency column wins over the catalogue's hint; series carrying neither
    # (volumes, CPI index points, FX) are left alone.
    if "currency" in df.columns:
        df = analysis.to_currency(df, currency, date_col)
    elif spec["currency"]:
        df = df.assign(currency=spec["currency"])
        df = analysis.to_currency(df, currency, date_col)

    s = pd.Series(
        pd.to_numeric(df["value"], errors="coerce").values,
        index=pd.to_datetime(df[date_col], errors="coerce"),
    ).dropna().sort_index()
    # Several rows can share a date (e.g. a state breakdown); collapse on the series' own
    # aggregation so the shape matches what resampling would have produced anyway.
    return s.groupby(level=0).agg(spec["agg"])


def matrix(specs: list[dict], freq: str, currency: str = "AUD") -> pd.DataFrame:
    """Resample every spec onto ``freq`` and return them as one wide frame."""
    rule = FREQ_RULES[freq]
    cols = {}
    for spec in specs:
        s = load(spec, currency)
        if s.empty:
            continue
        cols[spec["key"]] = s.resample(rule).agg(spec["agg"])
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def apply_lags(wide: pd.DataFrame, lags: dict[str, int]) -> pd.DataFrame:
    """Shift each column forward by its lag in periods (see the module docstring)."""
    out = wide.copy()
    for col, k in lags.items():
        if col in out.columns and k:
            out[col] = out[col].shift(k)
    return out


def _pair(wide: pd.DataFrame, ref: str, col: str, returns: bool) -> tuple[pd.Series, pd.Series]:
    pair = wide[[ref, col]]
    if returns:
        # replace(0, nan) first: a zero base makes pct_change explode to inf and poison r.
        pair = pair.replace(0, pd.NA).astype(float).pct_change(fill_method=None)
    return pair.dropna().iloc[:, 0], pair.dropna().iloc[:, 1]


def _corr(a: pd.Series, b: pd.Series, method: str) -> float | None:
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return None
    r = a.corr(b, method=method)
    return None if pd.isna(r) else float(r)


def metrics(wide: pd.DataFrame, ref: str) -> pd.DataFrame:
    """Per-series correlation against ``ref``, on levels and on percentage change."""
    rows = []
    for col in wide.columns:
        if col == ref:
            continue
        lv_a, lv_b = _pair(wide, ref, col, returns=False)
        rt_a, rt_b = _pair(wide, ref, col, returns=True)
        r_levels = _corr(lv_a, lv_b, "pearson")
        r_returns = _corr(rt_a, rt_b, "pearson")
        spurious = (
            r_levels is not None and r_returns is not None
            and abs(r_levels) - abs(r_returns) > SPURIOUS_GAP
        )
        rows.append({
            "series": col,
            "n": int(len(lv_a)),
            "pearson_levels": r_levels,
            "spearman_levels": _corr(lv_a, lv_b, "spearman"),
            "pearson_returns": r_returns,
            "spearman_returns": _corr(rt_a, rt_b, "spearman"),
            "trend_driven": spurious,
        })
    return pd.DataFrame(rows)


def cross_correlation(wide: pd.DataFrame, ref: str, col: str, max_lag: int) -> pd.DataFrame:
    """Correlation of ``col`` against ``ref`` at every lag in [-max_lag, +max_lag].

    Measured on percentage change, which is what makes a lag interpretable: it asks
    whether this series' moves precede the reference's, not whether both drift upward.
    """
    rows = []
    for k in range(-max_lag, max_lag + 1):
        shifted = wide[[ref, col]].copy()
        shifted[col] = shifted[col].shift(k)
        a, b = _pair(shifted, ref, col, returns=True)
        rows.append({"lag": k, "r": _corr(a, b, "pearson"), "n": int(len(a))})
    return pd.DataFrame(rows)


def best_lags(wide: pd.DataFrame, ref: str, max_lag: int, min_obs: int = 12) -> dict[str, int]:
    """Lag maximising |r| for each series against ``ref``.

    Lags whose overlap falls below ``min_obs`` are discarded: with a handful of points a
    spurious |r| near 1 always exists somewhere in the scan, and it would win.
    """
    out = {}
    for col in wide.columns:
        if col == ref:
            continue
        cc = cross_correlation(wide, ref, col, max_lag).dropna(subset=["r"])
        cc = cc[cc["n"] >= min_obs]
        if cc.empty:
            continue
        out[col] = int(cc.loc[cc["r"].abs().idxmax(), "lag"])
    return out


def rolling_correlation(wide: pd.DataFrame, ref: str, col: str, window: int) -> pd.DataFrame:
    """Rolling percentage-change correlation, for spotting a relationship that decays."""
    pair = wide[[ref, col]].replace(0, pd.NA).astype(float).pct_change(fill_method=None).dropna()
    if len(pair) < window:
        return pd.DataFrame()
    roll = pair[ref].rolling(window).corr(pair[col])
    return pd.DataFrame({"date": roll.index, "r": roll.values}).dropna()


def rebase(wide: pd.DataFrame, mode: str = "index") -> pd.DataFrame:
    """Put every column on one scale so they can share an axis.

    ``index`` rebases to 100 at each column's first observation (keeps relative moves
    readable); ``zscore`` standardises (better when levels differ by orders of magnitude).
    """
    out = wide.copy()
    for col in out.columns:
        s = out[col].dropna()
        if s.empty:
            continue
        if mode == "zscore":
            sd = s.std()
            out[col] = (out[col] - s.mean()) / sd if sd else out[col] - s.mean()
        else:
            base = s.iloc[0]
            out[col] = out[col] / base * 100 if base else out[col]
    return out
