"""SQLite persistence + Parquet export.

Tables are tidy/long and keyed on natural keys so re-running a refresh is idempotent
(``INSERT OR REPLACE``). Schemas are created on demand from the column set of the first
write, keeping the registry in config.py the single source of truth.
"""

from __future__ import annotations

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


def max_date(table: str, date_col: str) -> str | None:
    """Latest date stored for a table, or None if table is empty/missing."""
    with connect() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not row:
            return None
        result = conn.execute(f'SELECT MAX("{date_col}") FROM "{table}"').fetchone()
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


def export_parquet(table: str) -> None:
    df = read_table(table)
    if df.empty:
        return
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(config.PARQUET_DIR / f"{table}.parquet", index=False)
