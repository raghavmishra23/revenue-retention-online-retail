import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

import pandas as pd

from src.config import get, load_settings, resolve_path
from src.model.dimensions import (
    build_dim_country,
    build_dim_customer,
    build_dim_date,
    build_dim_product,
)
from src.model.facts import build_fact_sales
from src.utils.logging import get_logger
from src.warehouse import engine

REVENUE_TOLERANCE = 0.01
KEY_COLUMNS = ("date_key", "customer_key", "product_key", "country_key")
LOAD_ORDER = ("dim_date", "dim_customer", "dim_product", "dim_country", "fact_sales")
BATCH_ROWS = 50_000

log = get_logger(__name__)


def to_rows(frame: pd.DataFrame) -> list[tuple]:
    """Plain Python values with None for nulls; the driver cannot bind pd.NA."""
    clean = frame.astype(object).where(frame.notna(), None)
    return list(clean.itertuples(index=False, name=None))


def insert_frame(conn: sqlite3.Connection, table: str, frame: pd.DataFrame) -> None:
    columns = ", ".join(frame.columns)
    placeholders = ", ".join("?" * len(frame.columns))
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    for start in range(0, len(frame), BATCH_ROWS):
        conn.executemany(sql, to_rows(frame.iloc[start : start + BATCH_ROWS]))


def check_gates(conn: sqlite3.Connection, expected_rows: int, expected_revenue: float) -> None:
    null_keys = conn.execute(
        "SELECT COUNT(*) FROM fact_sales WHERE " + " OR ".join(f"{c} IS NULL" for c in KEY_COLUMNS)
    ).fetchone()[0]
    if null_keys:
        raise RuntimeError(f"{null_keys} fact_sales rows have a null surrogate key")

    violations = engine.foreign_key_violations(conn)
    if violations:
        raise RuntimeError(f"foreign_key_check returned {len(violations)} rows: {violations[:5]}")

    rows, revenue = conn.execute("SELECT COUNT(*), SUM(line_revenue) FROM fact_sales").fetchone()
    if rows != expected_rows:
        raise RuntimeError(f"fact_sales holds {rows} rows, expected {expected_rows}")
    if abs(revenue - expected_revenue) > REVENUE_TOLERANCE:
        raise RuntimeError(f"fact_sales revenue {revenue:.2f} != source {expected_revenue:.2f}")


def load_warehouse(
    conn: sqlite3.Connection,
    transactions: pd.DataFrame,
    regions: Mapping[str, str],
    unknown_customer_key: int,
    schema_dir: Path,
) -> dict[str, int]:
    """Rebuild every table from the transactions and run the integrity gates."""
    engine.assert_sqlite_version()
    dim_date = build_dim_date(transactions["invoice_ts"].min(), transactions["invoice_ts"].max())
    dim_customer = build_dim_customer(transactions, unknown_customer_key)
    dim_product = build_dim_product(transactions)
    dim_country = build_dim_country(transactions, regions)
    fact_sales = build_fact_sales(transactions, dim_customer, dim_product, dim_country)

    engine.apply_schema(conn, schema_dir)
    tables = dict(
        zip(LOAD_ORDER, (dim_date, dim_customer, dim_product, dim_country, fact_sales), strict=True)
    )
    for table, frame in tables.items():
        insert_frame(conn, table, frame)
    conn.commit()

    check_gates(conn, len(transactions), float(transactions["line_revenue"].sum()))
    counts = {table: len(frame) for table, frame in tables.items()}
    for table, count in counts.items():
        log.info("loaded %s rows into %s", count, table)
    return counts


def build_warehouse(path: Path | None = None) -> dict[str, int]:
    """Entry point: read the parquet, open the database, rebuild it."""
    settings = load_settings()
    transactions = pd.read_parquet(
        resolve_path("processed") / get(settings, "cleaning.transactions_filename")
    )
    with closing(engine.connect(path)) as conn:
        return load_warehouse(
            conn,
            transactions,
            get(settings, "country_regions"),
            get(settings, "warehouse.unknown_customer_key"),
            resolve_path("sql") / "01_schema",
        )
