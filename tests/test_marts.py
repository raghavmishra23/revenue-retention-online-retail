import hashlib
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from src.config import resolve_path
from src.model.dimensions import build_dim_date
from src.warehouse import engine
from src.warehouse.export import (
    Connection,
    assert_mart_gates,
    create_marts,
    export_marts,
    list_marts,
)

SCHEMA_DIR = resolve_path("sql") / "01_schema"
MART_DIR = resolve_path("sql") / "02_marts"
UNKNOWN_KEY = -1

PRODUCTS = [
    (1, "SKU-A", "ceramic bowl", "product"),
    (2, "SKU-B", "glass vase", "product"),
    (3, "POST", "postage", "shipping"),
    (4, "M", "manual adjustment", "adjustment"),
]
COUNTRIES = [(1, "United Kingdom", "United Kingdom"), (2, "France", "Europe")]

# dates of the kept orders and the value of each, chosen so every RFM segment lands populated
CUSTOMER_ORDERS: dict[int, tuple[list[str], float, int]] = {
    1: (["2011-02-01", "2011-03-01", "2011-04-01", "2011-05-01", "2011-06-15"], 100.0, 1),
    2: (["2011-02-02", "2011-03-02", "2011-04-02", "2011-05-02", "2011-06-10"], 90.0, 1),
    3: (["2011-01-03", "2011-02-03", "2011-04-03", "2011-06-05"], 80.0, 1),
    4: (["2011-03-04", "2011-05-25"], 60.0, 1),
    5: (["2011-01-05", "2011-03-05", "2011-05-20"], 70.0, 1),
    6: (["2011-04-06", "2011-05-10"], 50.0, 1),
    7: (["2011-01-07", "2011-02-07", "2011-04-20"], 45.0, 2),
    8: (["2011-04-10"], 30.0, 2),
    9: (["2011-01-09", "2011-01-19", "2011-02-09", "2011-03-15"], 150.0, 1),
    10: (["2011-02-10"], 20.0, 2),
}

FIXTURE_GROSS = 2750.0
FIXTURE_RETURNS = -90.0
FIXTURE_NET = 2660.0


def _fact_rows() -> list[tuple]:
    rows: list[tuple] = []

    def add(
        invoice_no: str,
        date: str,
        customer_key: int,
        product_key: int,
        country_key: int,
        unit_price: float,
        quantity: int = 1,
        is_cancellation: int = 0,
    ) -> None:
        rows.append(
            (
                len(rows) + 1,
                invoice_no,
                int(date.replace("-", "")),
                customer_key,
                product_key,
                country_key,
                f"{date}T10:00",
                quantity,
                unit_price,
                round(quantity * unit_price, 2),
                is_cancellation,
            )
        )

    for customer_key, (dates, value, country_key) in CUSTOMER_ORDERS.items():
        product_key = 2 if customer_key == 9 else 1
        for order, date in enumerate(dates, start=1):
            add(
                f"INV{customer_key:02d}{order}", date, customer_key, product_key, country_key, value
            )

    # a guest sale, a refund, a shipping line and an adjustment: the four cases the marts must sort
    add("INVGUEST", "2011-03-20", UNKNOWN_KEY, 1, 1, 250.0)
    add("CINV021", "2011-05-05", 2, 1, 1, 90.0, quantity=-1, is_cancellation=1)
    add("INV025", "2011-06-15", 1, 3, 1, 15.0)
    add("INVADJ", "2011-06-01", 1, 4, 1, 999.0)
    return rows


def build_fixture_warehouse(path: Path) -> Connection:
    """A handwritten star schema small enough to check every mart number by hand."""
    conn = engine.connect(path)
    engine.apply_schema(conn, SCHEMA_DIR)
    calendar = build_dim_date(pd.Timestamp("2011-01-01"), pd.Timestamp("2011-06-30"))
    conn.executemany(
        f"INSERT INTO dim_date VALUES ({', '.join('?' * len(calendar.columns))})",
        calendar.itertuples(index=False, name=None),
    )
    customers = [(UNKNOWN_KEY, None, None, None, None, None, 1)] + [
        (
            key,
            17000 + key,
            f"{dates[0]}T10:00",
            f"{dates[-1]}T10:00",
            0,
            COUNTRIES[country_key - 1][1],
            0,
        )
        for key, (dates, _, country_key) in CUSTOMER_ORDERS.items()
    ]
    conn.executemany("INSERT INTO dim_customer VALUES (?, ?, ?, ?, ?, ?, ?)", customers)
    conn.executemany("INSERT INTO dim_product VALUES (?, ?, ?, ?)", PRODUCTS)
    conn.executemany("INSERT INTO dim_country VALUES (?, ?, ?)", COUNTRIES)
    conn.executemany(
        "INSERT INTO fact_sales VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", _fact_rows()
    )
    conn.commit()
    create_marts(conn, MART_DIR)
    return conn


@pytest.fixture
def warehouse(tmp_path: Path) -> Iterator[Connection]:
    conn = build_fixture_warehouse(tmp_path / "fixture.sqlite")
    yield conn
    conn.close()


def test_every_mart_builds_and_clears_the_gates(warehouse: Connection) -> None:
    assert list_marts(warehouse) == [
        "mart_cohort_retention",
        "mart_country_performance",
        "mart_product_pareto",
        "mart_return_leakage",
        "mart_revenue_trend",
        "mart_rfm",
    ]
    assert_mart_gates(warehouse)


def test_recency_scores_reward_the_most_recent_customer(warehouse: Connection) -> None:
    scores = dict(warehouse.execute("SELECT customer_key, r_score FROM mart_rfm").fetchall())
    newest, oldest = scores[1], scores[10]

    assert newest == 5
    assert oldest == 1
    assert (
        warehouse.execute("SELECT recency_days FROM mart_rfm WHERE customer_key = 1").fetchone()[0]
        == 0
    )


def test_every_segment_is_populated_and_exclusive(warehouse: Connection) -> None:
    segments = dict(
        warehouse.execute("SELECT segment, COUNT(*) FROM mart_rfm GROUP BY segment").fetchall()
    )

    assert sum(segments.values()) == len(CUSTOMER_ORDERS)
    assert set(segments) == {
        "Champions",
        "Loyal",
        "Potential Loyalist",
        "At Risk",
        "Cannot Lose Them",
        "Hibernating",
        "Lost",
    }


def test_the_guest_member_never_becomes_a_customer(warehouse: Connection) -> None:
    assert warehouse.execute("SELECT COUNT(*) FROM mart_rfm").fetchone()[0] == len(CUSTOMER_ORDERS)
    assert (
        warehouse.execute(
            "SELECT COUNT(*) FROM mart_rfm WHERE customer_key = ?", (UNKNOWN_KEY,)
        ).fetchone()[0]
        == 0
    )
    cohort_members = warehouse.execute(
        "SELECT SUM(cohort_size) FROM mart_cohort_retention WHERE month_offset = 0"
    ).fetchone()[0]
    assert cohort_members == len(CUSTOMER_ORDERS)


def test_cohorts_start_at_full_retention_and_count_the_right_offset(
    warehouse: Connection,
) -> None:
    starts = warehouse.execute(
        "SELECT DISTINCT retention_pct FROM mart_cohort_retention WHERE month_offset = 0"
    ).fetchall()
    assert starts == [(100.0,)]

    # customers 5 and 9 both came back in March after a January first order
    size, active, retention = warehouse.execute(
        "SELECT cohort_size, active_customers, retention_pct FROM mart_cohort_retention "
        "WHERE cohort_month = '2011-01' AND month_offset = 2"
    ).fetchone()
    assert (size, active, retention) == (4, 2, 50.0)


def test_pareto_share_climbs_to_a_hundred(warehouse: Connection) -> None:
    curve = warehouse.execute(
        "SELECT cumulative_share_pct FROM mart_product_pareto ORDER BY revenue_rank"
    ).fetchall()
    shares = [share for (share,) in curve]

    assert len(shares) == 2
    assert shares[-1] == pytest.approx(100.0, abs=0.01)
    assert all(later >= earlier for earlier, later in zip(shares, shares[1:], strict=False))


def test_revenue_trend_months_sum_to_the_fixture(warehouse: Connection) -> None:
    months, gross, returns, net = warehouse.execute(
        "SELECT COUNT(*), SUM(gross_revenue), SUM(returns), SUM(net_revenue) "
        "FROM mart_revenue_trend"
    ).fetchone()

    assert months == 6
    assert gross == pytest.approx(FIXTURE_GROSS)
    assert returns == pytest.approx(FIXTURE_RETURNS)
    assert net == pytest.approx(FIXTURE_NET)


def test_country_mart_ties_to_the_same_gross(warehouse: Connection) -> None:
    gross = warehouse.execute("SELECT SUM(gross_revenue) FROM mart_country_performance").fetchone()[
        0
    ]
    assert gross == pytest.approx(FIXTURE_GROSS)


def test_gates_reject_scores_outside_the_quintiles(warehouse: Connection) -> None:
    warehouse.executescript(
        "DROP VIEW mart_rfm;"
        "CREATE VIEW mart_rfm AS SELECT customer_key, customer_id, 1 AS recency_days, "
        "1 AS frequency, 1.0 AS monetary, 9 AS r_score, 1 AS f_score, 1 AS m_score, "
        "'911' AS rfm_cell, 'Champions' AS segment FROM dim_customer WHERE is_guest = 0;"
    )

    with pytest.raises(RuntimeError, match="outside 1..5"):
        assert_mart_gates(warehouse)


def test_gates_reject_totals_that_drift_from_the_audit(warehouse: Connection) -> None:
    audited = {"gross_revenue": 1.0, "returns": -1.0, "net_revenue": 0.0}

    with pytest.raises(RuntimeError, match="!= audited"):
        assert_mart_gates(warehouse, audited)


def test_exports_are_byte_identical_across_runs(warehouse: Connection, tmp_path: Path) -> None:
    digests = []
    for run in ("first", "second"):
        target = tmp_path / run
        counts = export_marts(warehouse, target)
        digests.append(
            {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(target.glob("*.parquet"))
            }
        )

    assert counts["mart_rfm"] == len(CUSTOMER_ORDERS)
    assert len(digests[0]) == len(list_marts(warehouse))
    assert digests[0] == digests[1]
