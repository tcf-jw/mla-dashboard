"""The derived AUD 90CL series ships only when it agrees with MLA's manual series."""

import pandas as pd
import pytest

from mla_dashboard import analysis, config, db
from mla_dashboard.external import mla_90cl_manual
from mla_dashboard.external import mla_us_imported as m

AUD_USD = 0.65
US_C_PER_LB = 300.0
EXPECTED_AUD_C_PER_KG = US_C_PER_LB * 2.2046226218 / AUD_USD
WEEKS = pd.date_range("2026-01-02", periods=8, freq="7D")


@pytest.fixture
def written(tmp_path, monkeypatch):
    """Point the function at a temp parquet and flat FX; capture what it would upsert."""
    fx = pd.DataFrame({"date": pd.date_range("2025-12-01", "2026-03-31"), "aud_usd": AUD_USD})
    monkeypatch.setattr(config, "PARQUET_DIR", tmp_path)
    monkeypatch.setattr(analysis, "load_fx", lambda: fx.copy())
    calls = []
    monkeypatch.setattr(db, "upsert", lambda table, df, pk: calls.append(df) or len(df))
    monkeypatch.setattr(db, "export_parquet", lambda table: None)
    return calls


def write_snapshot(path, manual_factor):
    steiner = pd.DataFrame({
        "result_date": WEEKS.strftime("%Y-%m-%d"), "value": US_C_PER_LB,
        "grade": m.PARITY_GRADE, "series": m.SERIES, "unit": "US c/lb", "currency": "USD",
    })
    manual = pd.DataFrame({
        "result_date": WEEKS.strftime("%Y-%m-%d"), "value": EXPECTED_AUD_C_PER_KG * manual_factor,
        "grade": "90CL", "series": mla_90cl_manual.SERIES, "unit": "AU c/kg", "currency": "AUD",
    })
    pd.concat([steiner, manual]).to_parquet(path / f"{m.TABLE}.parquet", index=False)


def test_writes_when_within_two_percent(tmp_path, written):
    write_snapshot(tmp_path, manual_factor=1.01)
    assert m.derive_aud_90cl() == len(WEEKS)
    out = written[0]
    assert set(out["series"]) == {m.DERIVED_SERIES}
    assert set(out["grade"]) == {"90CL"}
    assert out["value"].tolist() == pytest.approx([EXPECTED_AUD_C_PER_KG] * len(WEEKS))


def test_refuses_when_over_two_percent(tmp_path, written):
    write_snapshot(tmp_path, manual_factor=1.05)
    assert m.derive_aud_90cl() == 0
    assert written == []


def test_no_snapshot_writes_nothing(written):
    assert m.derive_aud_90cl() == 0
    assert written == []
