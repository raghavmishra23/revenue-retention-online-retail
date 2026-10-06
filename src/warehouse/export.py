from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from src.config import get, load_settings, resolve_path
from src.utils.logging import get_logger
from src.warehouse import engine

SEGMENTS = (
    "Champions",
    "Loyal",
    "Potential Loyalist",
    "At Risk",
    "Cannot Lose Them",
    "Hibernating",
    "Lost",
)

log = get_logger(__name__)


class Connection(Protocol):
    """The slice of the driver the marts need, so only the engine imports sqlite3."""

    def execute(self, sql: str, *parameters: Any) -> Any: ...

    def executescript(self, sql: str) -> Any: ...

    def commit(self) -> None: ...


def _scalar(conn: Connection, sql: str) -> Any:
    return conn.execute(sql).fetchone()[0]


def _sales_line_filter() -> str:
    """The revenue definition lives in settings, so Python and the mart SQL cannot disagree."""
    line_types = get(load_settings(), "cleaning.net_revenue_line_types")
    return ", ".join(f"'{line_type}'" for line_type in line_types)


def list_marts(conn: Connection) -> list[str]:
    prefix = get(load_settings(), "marts.view_prefix")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE ? ORDER BY name",
        (f"{prefix}%",),
    ).fetchall()
    return [name for (name,) in rows]


def create_marts(conn: Connection, directory: Path) -> list[str]:
    """Run every mart script in filename order and return the view names now defined."""
    for script in sorted(directory.glob("*.sql")):
        conn.executescript(script.read_text(encoding="utf-8"))
    conn.commit()
    return list_marts(conn)


def read_mart(conn: Connection, view: str) -> pd.DataFrame:
    frame = pd.read_sql_query(f"SELECT * FROM {view}", conn)
    # sorting on every column pins the row order, so a rebuild writes identical parquet
    return frame.sort_values(list(frame.columns), kind="stable").reset_index(drop=True)


def export_marts(conn: Connection, output_dir: Path) -> dict[str, int]:
    """Write each mart view to parquet and return the row count per mart."""
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for view in list_marts(conn):
        frame = read_mart(conn, view)
        frame.to_parquet(output_dir / f"{view}.parquet", index=False)
        counts[view] = len(frame)
    return counts


def _assert_rfm(conn: Connection) -> None:
    out_of_range = _scalar(
        conn,
        "SELECT COUNT(*) FROM mart_rfm WHERE r_score NOT BETWEEN 1 AND 5 "
        "OR f_score NOT BETWEEN 1 AND 5 OR m_score NOT BETWEEN 1 AND 5",
    )
    if out_of_range:
        raise RuntimeError(f"{out_of_range} rfm rows score outside 1..5")

    duplicates = _scalar(
        conn,
        "SELECT COUNT(*) FROM (SELECT customer_key FROM mart_rfm "
        "GROUP BY customer_key HAVING COUNT(*) > 1)",
    )
    if duplicates:
        raise RuntimeError(f"{duplicates} customers appear more than once in mart_rfm")

    unsegmented = _scalar(conn, "SELECT COUNT(*) FROM mart_rfm WHERE segment IS NULL")
    if unsegmented:
        raise RuntimeError(f"{unsegmented} rfm rows fell through the segment rules")

    # every real customer with a kept sales line has to be scored, and nobody else
    scored = _scalar(conn, "SELECT COUNT(*) FROM mart_rfm")
    eligible = _scalar(
        conn,
        "SELECT COUNT(DISTINCT f.customer_key) FROM fact_sales f "
        "JOIN dim_product p ON p.product_key = f.product_key "
        "JOIN dim_customer c ON c.customer_key = f.customer_key "
        f"WHERE p.line_type IN ({_sales_line_filter()}) AND c.is_guest = 0 "
        "AND f.is_cancellation = 0",
    )
    if scored != eligible:
        raise RuntimeError(f"mart_rfm scores {scored} customers, warehouse has {eligible}")

    found = {name for (name,) in conn.execute("SELECT DISTINCT segment FROM mart_rfm")}
    missing = [segment for segment in SEGMENTS if segment not in found]
    if missing:
        raise RuntimeError(f"segments with no customers: {missing}")
    if found - set(SEGMENTS):
        raise RuntimeError(f"unexpected segments: {sorted(found - set(SEGMENTS))}")


def _assert_cohort(conn: Connection) -> None:
    broken_start = _scalar(
        conn,
        "SELECT COUNT(*) FROM mart_cohort_retention "
        "WHERE month_offset = 0 AND retention_pct <> 100.0",
    )
    if broken_start:
        raise RuntimeError(f"{broken_start} cohorts do not start at 100% retention")

    impossible = _scalar(
        conn, "SELECT COUNT(*) FROM mart_cohort_retention WHERE active_customers > cohort_size"
    )
    if impossible:
        raise RuntimeError(f"{impossible} cohort cells hold more actives than the cohort size")


def _assert_pareto(conn: Connection, tolerance: float) -> None:
    final_share = _scalar(
        conn,
        "SELECT cumulative_share_pct FROM mart_product_pareto "
        "ORDER BY revenue_rank DESC LIMIT 1",
    )
    if abs(final_share - 100.0) > tolerance:
        raise RuntimeError(f"pareto cumulative share ends at {final_share:.4f}, not 100")

    # the curve may only fall where a SKU nets negative, which is the one honest exception
    backwards = _scalar(
        conn,
        "SELECT COUNT(*) FROM (SELECT net_revenue, "
        "cumulative_share_pct - LAG(cumulative_share_pct) "
        "OVER (ORDER BY revenue_rank) AS step FROM mart_product_pareto) "
        "WHERE step IS NOT NULL AND net_revenue >= 0 AND step < -1e-9",
    )
    if backwards:
        raise RuntimeError(f"pareto cumulative share drops at {backwards} profitable SKUs")


def _warehouse_totals(conn: Connection) -> tuple[float, float, float]:
    return conn.execute(
        "SELECT SUM(CASE WHEN f.is_cancellation = 0 THEN f.line_revenue ELSE 0 END), "
        "SUM(CASE WHEN f.is_cancellation = 1 THEN f.line_revenue ELSE 0 END), "
        "SUM(f.line_revenue) FROM fact_sales f "
        "JOIN dim_product p ON p.product_key = f.product_key "
        f"WHERE p.line_type IN ({_sales_line_filter()})"
    ).fetchone()


def _assert_totals(
    conn: Connection, tolerance: float, expected: Mapping[str, float] | None
) -> None:
    gross, returns, net = _warehouse_totals(conn)
    trend = conn.execute(
        "SELECT SUM(gross_revenue), SUM(returns), SUM(net_revenue) FROM mart_revenue_trend"
    ).fetchone()
    for name, mart_value, warehouse_value in zip(
        ("gross_revenue", "returns", "net_revenue"), trend, (gross, returns, net), strict=True
    ):
        if abs(mart_value - warehouse_value) > tolerance:
            raise RuntimeError(
                f"mart_revenue_trend {name} {mart_value:.2f} != warehouse {warehouse_value:.2f}"
            )

    country_gross = _scalar(conn, "SELECT SUM(gross_revenue) FROM mart_country_performance")
    if abs(country_gross - gross) > tolerance:
        raise RuntimeError(
            f"mart_country_performance gross {country_gross:.2f} != warehouse {gross:.2f}"
        )

    if expected is None:
        return
    for name, warehouse_value in zip(
        ("gross_revenue", "returns", "net_revenue"), (gross, returns, net), strict=True
    ):
        if abs(warehouse_value - expected[name]) > tolerance:
            raise RuntimeError(
                f"warehouse {name} {warehouse_value:.2f} != audited {expected[name]:.2f}"
            )


def assert_mart_gates(conn: Connection, expected: Mapping[str, float] | None = None) -> None:
    """Raise rather than export a plausible wrong number; `expected` pins the audited totals."""
    tolerance = get(load_settings(), "marts.revenue_tolerance")
    _assert_rfm(conn)
    _assert_cohort(conn)
    _assert_pareto(conn, tolerance)
    _assert_totals(conn, tolerance, expected)


def build_marts(path: Path | None = None) -> dict[str, int]:
    """Entry point: create the mart views, run the gates, then export parquet."""
    settings = load_settings()
    sql_root = resolve_path("sql")
    with closing(engine.connect(path)) as conn:
        views: Sequence[str] = create_marts(conn, sql_root / get(settings, "marts.sql_subdir"))
        log.info("created %s mart views: %s", len(views), ", ".join(views))
        assert_mart_gates(conn, get(settings, "marts.expected_totals"))
        counts = export_marts(conn, resolve_path("marts"))
    for view, rows in counts.items():
        log.info("exported %s rows to %s.parquet", rows, view)
    return counts
