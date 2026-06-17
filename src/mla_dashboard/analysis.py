"""Derived series and currency conversion consumed by the dashboard.

All price values are stored in their native currency (see the ``currency`` column).
``to_currency`` converts a price frame to a target currency using date-matched FX, so a
2015 price is converted with the 2015 rate, not today's spot.
"""

from __future__ import annotations

import pandas as pd

from . import db


# Resample frequency labels -> pandas offset aliases.
FREQ = {"Daily": "D", "Weekly": "W", "Monthly": "MS", "Yearly": "YS"}

# Lookback windows -> number of days back from the latest date (None = all history).
WINDOWS = {
    "Last 7 days": 7,
    "Last 14 days": 14,
    "Last 4 weeks": 28,
    "Last quarter": 91,
    "Last year": 365,
    "All": None,
}

# How each kind of series should be aggregated when resampling.
# Prices are averaged; volumes/counts are summed.
MEAN = "mean"
SUM = "sum"


def apply_window(df: pd.DataFrame, date_col: str, days: int | None) -> pd.DataFrame:
    """Keep only rows within ``days`` of the latest date. None = no filtering."""
    if df.empty or days is None:
        return df
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    cutoff = d[date_col].max() - pd.Timedelta(days=days)
    return d[d[date_col] >= cutoff]


def resample(
    df: pd.DataFrame,
    date_col: str,
    freq_label: str,
    how: str,
    value_col: str = "value",
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Resample to a frequency, aggregating ``value_col`` by ``how`` (mean/sum).

    Preserves ``group_cols`` (e.g. indicator label, category) so multi-series charts
    keep their split. Daily frequency is a passthrough.
    """
    if df.empty or freq_label == "Daily":
        return df
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    rule = FREQ[freq_label]
    group_cols = group_cols or []

    def _agg(g: pd.DataFrame) -> pd.DataFrame:
        return g.set_index(date_col)[value_col].resample(rule).agg(how).reset_index()

    if group_cols:
        parts = []
        for keys, g in d.groupby(group_cols):
            part = _agg(g)
            keys = keys if isinstance(keys, tuple) else (keys,)
            for col, val in zip(group_cols, keys):
                part[col] = val
            parts.append(part)
        out = pd.concat(parts, ignore_index=True)
    else:
        out = _agg(d)
    return out.dropna(subset=[value_col])


def load_fx() -> pd.DataFrame:
    fx = db.read_table("fx_rates")
    if fx.empty:
        return fx
    fx["date"] = pd.to_datetime(fx["date"])
    fx = fx.sort_values("date")
    return fx


def to_currency(
    df: pd.DataFrame, target: str, date_col: str, value_col: str = "value"
) -> pd.DataFrame:
    """Convert ``value_col`` to ``target`` (AUD/USD) using date-matched AUD/USD rates.

    Rows whose ``currency`` already equals ``target`` pass through unchanged. Missing FX
    dates are forward-filled (FX is business-day only).
    """
    if df.empty or "currency" not in df.columns:
        return df
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    fx = load_fx()
    if fx.empty:
        return out  # no FX available: leave values in native currency
    out = pd.merge_asof(
        out.sort_values(date_col), fx, left_on=date_col, right_on="date", direction="nearest"
    )

    def convert(row):
        cur, val, rate = row["currency"], row[value_col], row["aud_usd"]
        if pd.isna(val) or pd.isna(rate) or cur == target:
            return val
        if cur == "AUD" and target == "USD":
            return val * rate
        if cur == "USD" and target == "AUD":
            return val / rate
        return val

    out[value_col] = out.apply(convert, axis=1)
    return out.drop(columns=["date", "aud_usd"], errors="ignore")


def indicator_series(indicator_id: int, currency: str = "AUD") -> pd.DataFrame:
    df = db.read_table("indicators")
    if df.empty:
        return df
    df = df[df["indicator_id"] == indicator_id]
    df = to_currency(df, currency, "calendar_date")
    return df.sort_values("calendar_date")


def add_rolling_yoy(df: pd.DataFrame, date_col: str, value_col: str = "value") -> pd.DataFrame:
    out = df.sort_values(date_col).copy()
    out["rolling_30d"] = out[value_col].rolling(30, min_periods=1).mean()
    out["yoy_pct"] = out[value_col].pct_change(periods=252) * 100  # ~1 trading yr
    return out


# Species -> (slaughter/production categories, indicator species_id). Lets the dashboard
# filter both the price indicator and the supply category to the same species.
SPECIES_MAP = {
    "Cattle": {
        "categories": [
            "Cattle (Excl. Calves)", "Cows And Heifers",
            "Bulls, Bullocks And Steers", "Calves",
        ],
        "indicator_species": "Cattle",
    },
    "Sheep": {
        "categories": ["Sheep", "Lambs"],
        "indicator_species": "Sheep",
    },
}


def indicators_for_species(species: str) -> pd.DataFrame:
    """Indicator id/desc rows whose species matches (for the price dropdown)."""
    df = db.read_table("indicators")
    if df.empty:
        return df
    target = SPECIES_MAP.get(species, {}).get("indicator_species", species)
    sub = df[df["species_id"] == target]
    return sub[["indicator_id", "indicator_desc"]].drop_duplicates()


def supply_vs_price(
    indicator_id: int,
    category: str,
    currency: str = "AUD",
    report_type: str = "Slaughter",
    location: str = "Australia",
) -> pd.DataFrame:
    """Monthly price (mean) vs supply volume (national), aligned by month.

    Returns columns: month, price, volume, unit. Empty if either side missing.
    """
    price = indicator_series(indicator_id, currency)
    sup = db.read_table("slaughter_production")
    if price.empty or sup.empty:
        return pd.DataFrame()
    sup = sup[
        (sup["category"] == category)
        & (sup["report_type"] == report_type)
        & (sup["location_id"] == location)
    ].copy()
    if sup.empty:
        return pd.DataFrame()
    price_m = (
        price.assign(month=pd.to_datetime(price["calendar_date"]).dt.to_period("M"))
        .groupby("month")["value"].mean().rename("price")
    )
    sup["month"] = pd.to_datetime(sup["report_date"]).dt.to_period("M")
    vol_m = sup.groupby("month")["value"].sum().rename("volume")
    out = pd.concat([price_m, vol_m], axis=1).dropna().reset_index()
    out["month"] = out["month"].dt.to_timestamp()
    out["unit"] = sup["unit"].iloc[0] if "unit" in sup else ""
    return out


def au_vs_global_spread(au_indicator_id: int, currency: str = "USD") -> pd.DataFrame:
    """Monthly mean AU indicator vs global cattle price, both in one currency."""
    au = indicator_series(au_indicator_id, currency)
    gl = db.read_table("global_cattle_prices")
    if au.empty or gl.empty:
        return pd.DataFrame()
    gl = to_currency(gl, currency, "indicator_date")
    au_m = (
        au.assign(month=pd.to_datetime(au["calendar_date"]).dt.to_period("M"))
        .groupby("month")["value"].mean().rename("au")
    )
    gl_m = (
        gl.assign(month=pd.to_datetime(gl["indicator_date"]).dt.to_period("M"))
        .groupby("month")["value"].mean().rename("global")
    )
    out = pd.concat([au_m, gl_m], axis=1).dropna()
    out["spread"] = out["au"] - out["global"]
    return out.reset_index().assign(month=lambda d: d["month"].dt.to_timestamp())
