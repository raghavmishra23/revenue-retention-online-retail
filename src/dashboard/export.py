"""Shape the marts into the single JSON payload the dashboard page reads."""

import json
from pathlib import Path
from typing import Any

from src.config import get, load_settings, resolve_path
from src.utils.logging import get_logger
from src.warehouse.engine import connect

log = get_logger(__name__)

# the curve is 4,746 points and a line chart cannot show that, so I thin it for drawing only
PARETO_CURVE_POINTS = 240
TOP_PRODUCTS = 20
TOP_LEAKAGE = 12


def _rows(conn: Any, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one(conn: Any, sql: str) -> dict[str, Any]:
    return _rows(conn, sql)[0]


def headline_kpis(conn: Any) -> dict[str, Any]:
    """The KPI row: totals over the whole period, plus the two growth rates."""
    totals = _one(
        conn,
        """
        SELECT ROUND(SUM(gross_revenue), 2) AS gross_revenue,
               ROUND(SUM(returns), 2)       AS returns,
               ROUND(SUM(net_revenue), 2)   AS net_revenue,
               SUM(orders)                  AS orders
        FROM mart_revenue_trend
        """,
    )
    customers = _one(
        conn,
        """
        SELECT COUNT(*)                          AS active_customers,
               ROUND(AVG(monetary), 2)           AS average_clv,
               ROUND(100.0 * SUM(CASE WHEN frequency > 1 THEN 1 ELSE 0 END) / COUNT(*), 2)
                                                 AS repeat_purchase_rate_pct
        FROM mart_rfm
        """,
    )
    # two clean 12-month windows, so the partial final month cannot distort the comparison
    yoy = _one(
        conn,
        """
        WITH windows AS (
            SELECT SUM(CASE WHEN year_month BETWEEN '2010-12' AND '2011-11'
                            THEN net_revenue END) AS recent,
                   SUM(CASE WHEN year_month BETWEEN '2009-12' AND '2010-11'
                            THEN net_revenue END) AS prior
            FROM mart_revenue_trend
        )
        SELECT ROUND(recent, 2) AS recent_year_net,
               ROUND(prior, 2)  AS prior_year_net,
               ROUND(100.0 * (recent - prior) / prior, 2) AS revenue_yoy_pct
        FROM windows
        """,
    )
    latest = _one(
        conn,
        """
        SELECT year_month, ROUND(net_revenue_mom_pct, 2) AS revenue_mom_pct
        FROM mart_revenue_trend
        ORDER BY year_month DESC LIMIT 1
        """,
    )
    gross, returns = totals["gross_revenue"], totals["returns"]
    return {
        **totals,
        **customers,
        **yoy,
        "latest_month": latest["year_month"],
        "revenue_mom_pct": latest["revenue_mom_pct"],
        "return_rate_pct": round(-returns / gross * 100, 4),
        "aov": round(gross / totals["orders"], 2),
    }


def rfm_matrix(conn: Any) -> list[dict[str, Any]]:
    """The 5x5 recency-by-frequency grid, which is how the segments are actually read."""
    return _rows(
        conn,
        """
        SELECT r_score, f_score, COUNT(*) AS customers, ROUND(SUM(monetary), 2) AS net_revenue
        FROM mart_rfm GROUP BY r_score, f_score ORDER BY r_score, f_score
        """,
    )


def rfm_segments(conn: Any) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT segment,
               COUNT(*)                        AS customers,
               ROUND(SUM(monetary), 2)         AS net_revenue,
               ROUND(AVG(monetary), 2)         AS average_value,
               ROUND(AVG(recency_days), 1)     AS average_recency_days,
               ROUND(AVG(frequency), 1)        AS average_orders
        FROM mart_rfm GROUP BY segment ORDER BY net_revenue DESC
        """,
    )


def pareto_curve(conn: Any) -> dict[str, Any]:
    """Thin the concentration curve for drawing, but take the 80% crossing from every row."""
    crossing = _one(
        conn,
        """
        SELECT MIN(revenue_rank) AS rank_at_80, COUNT(*) AS total_skus
        FROM mart_product_pareto
        WHERE cumulative_share_pct >= 80.0
        """,
    )
    total = _one(conn, "SELECT COUNT(*) AS total_skus FROM mart_product_pareto")["total_skus"]
    step = max(1, total // PARETO_CURVE_POINTS)
    curve = _rows(
        conn,
        f"""
        SELECT revenue_rank, ROUND(cumulative_share_pct, 3) AS cumulative_share_pct
        FROM mart_product_pareto
        WHERE revenue_rank % {step} = 0 OR revenue_rank IN (1, {total})
        ORDER BY revenue_rank
        """,
    )
    band = _one(
        conn,
        """
        SELECT COUNT(*) AS skus, ROUND(SUM(net_revenue), 2) AS net_revenue
        FROM mart_product_pareto WHERE in_top_80_band = 1
        """,
    )
    return {
        "curve": curve,
        "total_skus": total,
        "rank_at_80": crossing["rank_at_80"],
        "band_skus": band["skus"],
        "band_net_revenue": band["net_revenue"],
    }


def same_day_reversals(conn: Any) -> dict[str, Any]:
    """Cancellations that undo an identical sale the same day: entry corrections, not returns."""
    return _one(
        conn,
        """
        WITH sales AS (
            SELECT f.customer_key, f.product_key, f.quantity, f.line_revenue,
                   f.is_cancellation, SUBSTR(f.invoice_ts, 1, 10) AS sale_day
            FROM fact_sales f
            JOIN dim_product p ON p.product_key = f.product_key
            WHERE p.line_type IN ('product', 'shipping')
        ),
        reversed AS (
            -- an exact opposite quantity for the same customer, SKU and day
            SELECT c.line_revenue
            FROM sales c
            WHERE c.is_cancellation = 1 AND EXISTS (
                SELECT 1 FROM sales s
                WHERE s.is_cancellation = 0
                  AND s.customer_key = c.customer_key
                  AND s.product_key = c.product_key
                  AND s.sale_day = c.sale_day
                  AND s.quantity = -c.quantity
            )
        )
        SELECT COUNT(*) AS lines, ROUND(SUM(line_revenue), 2) AS value FROM reversed
        """,
    )


def build_payload(conn: Any) -> dict[str, Any]:
    settings = load_settings()
    return {
        "meta": {
            "currency": get(settings, "project.currency"),
            "currency_symbol": get(settings, "project.currency_symbol"),
            "period": _one(
                conn,
                "SELECT MIN(year_month) AS start, MAX(year_month) AS end FROM mart_revenue_trend",
            ),
        },
        "kpis": headline_kpis(conn),
        "revenue_trend": _rows(
            conn,
            """
            SELECT year_month, ROUND(gross_revenue, 2) AS gross_revenue,
                   ROUND(returns, 2) AS returns, ROUND(net_revenue, 2) AS net_revenue,
                   orders, active_customers, ROUND(aov, 2) AS aov,
                   ROUND(return_rate_pct, 2) AS return_rate_pct,
                   ROUND(net_revenue_mom_pct, 2) AS net_revenue_mom_pct
            FROM mart_revenue_trend ORDER BY year_month
            """,
        ),
        "countries": _rows(
            conn,
            """
            SELECT country, region, ROUND(gross_revenue, 2) AS gross_revenue,
                   ROUND(net_revenue, 2) AS net_revenue, orders, customers,
                   ROUND(aov, 2) AS aov, ROUND(return_rate_pct, 2) AS return_rate_pct,
                   revenue_rank
            FROM mart_country_performance ORDER BY revenue_rank
            """,
        ),
        "regions": _rows(
            conn,
            """
            SELECT region, ROUND(SUM(net_revenue), 2) AS net_revenue, SUM(customers) AS customers
            FROM mart_country_performance GROUP BY region ORDER BY net_revenue DESC
            """,
        ),
        "rfm_segments": rfm_segments(conn),
        "rfm_matrix": rfm_matrix(conn),
        "cohort": _rows(
            conn,
            """
            SELECT cohort_month, month_offset, cohort_size, active_customers,
                   ROUND(retention_pct, 2) AS retention_pct
            FROM mart_cohort_retention ORDER BY cohort_month, month_offset
            """,
        ),
        "pareto": pareto_curve(conn),
        "same_day_reversals": same_day_reversals(conn),
        "top_products": _rows(
            conn,
            f"""
            SELECT stock_code, description, ROUND(net_revenue, 2) AS net_revenue, units, orders
            FROM mart_product_pareto ORDER BY revenue_rank LIMIT {TOP_PRODUCTS}
            """,
        ),
        "return_drivers": _rows(
            conn,
            f"""
            SELECT grain_value AS stock_code, ROUND(returns, 2) AS returns,
                   ROUND(return_rate_pct, 2) AS return_rate_pct, return_lines
            FROM mart_return_leakage WHERE grain = 'product' AND returns < 0
            ORDER BY returns LIMIT {TOP_LEAKAGE}
            """,
        ),
    }


def export_dashboard_data(output_path: Path | None = None) -> Path:
    """Write the payload as a script that assigns a global.

    A plain .json would need fetch(), and fetch() is blocked on file:// origins, so the
    dashboard would only open through a web server. Assigning a global keeps it openable
    by double-clicking index.html.
    """
    target = output_path or resolve_path("dashboard_data")
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        payload = build_payload(conn)
    body = json.dumps(payload, indent=2, sort_keys=True)
    target.write_text("window.DASHBOARD_DATA = " + body + ";\n", encoding="utf-8")
    log.info("wrote %s (%.0f KB)", target, target.stat().st_size / 1024)
    return target
