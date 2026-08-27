"""SQLite persistence + Parquet export.

Tables are tidy/long and keyed on natural keys so re-running a refresh is idempotent
(``INSERT OR REPLACE``). Schemas are created on demand from the column set of the first
write, keeping the registry in config.py the single source of truth.
"""

from __future__ import annotations

import pathlib
import sqlite3
from contextlib import contextmanager

import pandas as pd

from . import config


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    # WAL + a busy timeout let the dashboard read while a refresh writes, instead of
    # failing with "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _create_table(conn: sqlite3.Connection, table: str, columns: list[str], pk: list[str]):
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    pk_sql = ", ".join(f'"{c}"' for c in pk) if pk else ""
    constraint = f", PRIMARY KEY ({pk_sql})" if pk_sql else ""
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_sql}{constraint})')


def upsert(table: str, df: pd.DataFrame, pk: list[str]) -> int:
    """Insert-or-replace ``df`` into ``table``. Returns rows written."""
    if df.empty:
        return 0
    columns = list(df.columns)
    placeholders = ", ".join("?" for _ in columns)
    col_sql = ", ".join(f'"{c}"' for c in columns)
    with connect() as conn:
        _create_table(conn, table, columns, [c for c in pk if c in columns])
        conn.executemany(
            f'INSERT OR REPLACE INTO "{table}" ({col_sql}) VALUES ({placeholders})',
            df.itertuples(index=False, name=None),
        )
    return len(df)


def max_date(
    table: str, date_col: str, where_col: str | None = None, where_val: str | None = None
) -> str | None:
    """Latest date stored for a table, or None if table is empty/missing.

    ``where_col``/``where_val`` narrow the scan to one slice - needed where several
    sources share a table (e.g. ``lean_beef_prices``) and each must top up from its own
    latest date rather than the table-wide maximum.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not row:
            return None
        sql = f'SELECT MAX("{date_col}") FROM "{table}"'
        params: tuple = ()
        if where_col is not None:
            sql += f' WHERE "{where_col}" = ?'
            params = (where_val,)
        result = conn.execute(sql, params).fetchone()
    return result[0] if result and result[0] else None


def read_table(table: str) -> pd.DataFrame:
    """Read a table from SQLite, falling back to the committed Parquet snapshot.

    The Parquet fallback lets the dashboard run from a repo that ships only
    ``data/parquet/`` (e.g. Streamlit Community Cloud) with no local mla.db.
    """
    if config.DB_PATH.exists():
        with connect() as conn:
            try:
                return pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            except pd.errors.DatabaseError:
                pass
    parquet = config.PARQUET_DIR / f"{table}.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    return pd.DataFrame()


# Reference lookups predate the natural-key convention and carry no PRIMARY KEY, so
# their id column has to be named here for the merge in export_parquet.
_FALLBACK_KEYS = {"ref_indicator": ["indicator_id"], "ref_saleyard": ["saleyard_id"]}


def primary_key(table: str) -> list[str]:
    """Natural-key columns for a table, in key order. Empty if it declares none."""
    with connect() as conn:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    # PRAGMA table_info gives (cid, name, type, notnull, dflt_value, pk), where pk is the
    # 1-based position within the primary key and 0 for every non-key column.
    key = [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: r[5])]
    return key or _FALLBACK_KEYS.get(table, [])


def export_parquet(table: str) -> None:
    """Merge the stored table into the committed Parquet snapshot and rewrite it.

    The snapshot accumulates rather than being replaced. CI checks out a repo with no
    mla.db (it is gitignored so a stale copy cannot shadow the Parquet on Streamlit
    Cloud), so every table there cold-starts from config.BACKFILL_START and rebuilds
    thinner than the committed file. A plain overwrite silently discarded the
    difference: lean_beef_prices lost its 2000-2009 Steiner history and the whole
    manual MLA series (18,783 -> 9,818 rows) about 20 hours after each restore, and the
    reference lookups shrank the same way.

    Merging on the natural key keeps history the current backfill window cannot reach,
    while the fresh rows still win on collision so revisions land. The trade-off is that
    a row genuinely withdrawn upstream is never removed from the snapshot; a --backfill
    run rewrites the affected span, and the file can always be rebuilt from scratch by
    deleting it.
    """
    df = read_table(table)
    if df.empty:
        return
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    target = config.PARQUET_DIR / f"{table}.parquet"

    key = primary_key(table)
    if key and target.exists():
        prior = pd.read_parquet(target)
        # A schema change makes the two frames unalignable; take the fresh one rather
        # than concatenating mismatched columns into a frame full of NaN.
        if not prior.empty and list(prior.columns) == list(df.columns):
            df = (
                pd.concat([prior, df], ignore_index=True)
                .drop_duplicates(subset=key, keep="last")
                .sort_values(key)
                .reset_index(drop=True)
            )

    df.to_parquet(target, index=False)


if __name__ == "__main__":  # self-check: python -m mla_dashboard.db
    import tempfile

    _prior = pd.DataFrame({"k": ["a", "b"], "d": ["2000-01-01", "2000-01-02"], "v": [1, 2]})
    _fresh = pd.DataFrame({"k": ["b", "c"], "d": ["2000-01-02", "2000-01-03"], "v": [99, 3]})
    _merged = (
        pd.concat([_prior, _fresh], ignore_index=True)
        .drop_duplicates(subset=["k"], keep="last")
        .sort_values(["k"])
        .reset_index(drop=True)
    )
    # history the fresh pull could not reach survives...
    assert list(_merged["k"]) == ["a", "b", "c"], _merged
    # ...and a revision to an existing key wins over the stored value.
    assert _merged.loc[_merged["k"] == "b", "v"].item() == 99, _merged

    # primary_key reads the declared key in key order, and falls back for the ref tables.
    with tempfile.TemporaryDirectory() as _tmp:
        _orig_db, _orig_pq = config.DB_PATH, config.PARQUET_DIR
        config.DB_PATH = pathlib.Path(_tmp) / "t.db"
        config.PARQUET_DIR = pathlib.Path(_tmp) / "parquet"
        try:
            with connect() as _c:
                _c.execute('CREATE TABLE t ("a", "b", "d", PRIMARY KEY ("b", "a"))')
            assert primary_key("t") == ["b", "a"], primary_key("t")
            assert primary_key("ref_saleyard") == ["saleyard_id"]
            assert primary_key("nope") == []
        finally:
            config.DB_PATH, config.PARQUET_DIR = _orig_db, _orig_pq
    print("db self-check ok")
