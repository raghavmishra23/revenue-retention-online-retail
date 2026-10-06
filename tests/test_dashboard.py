"""The dashboard payload has to agree with the marts it is shaped from."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.dashboard import export as dashboard
from tests.test_marts import Connection, build_fixture_warehouse


@pytest.fixture
def warehouse(tmp_path: Path) -> Iterator[Connection]:
    conn = build_fixture_warehouse(tmp_path / "fixture.sqlite")
    yield conn
    conn.close()


def test_payload_carries_every_section_the_page_reads(warehouse: Connection) -> None:
    payload = dashboard.build_payload(warehouse)
    expected = {
        "meta",
        "kpis",
        "revenue_trend",
        "countries",
        "regions",
        "rfm_segments",
        "rfm_matrix",
        "cohort",
        "pareto",
        "same_day_reversals",
        "top_products",
        "return_drivers",
    }
    assert expected <= set(payload)


def test_headline_revenue_matches_the_trend_mart(warehouse: Connection) -> None:
    kpis = dashboard.headline_kpis(warehouse)
    trend = warehouse.execute(
        "SELECT ROUND(SUM(gross_revenue), 2), ROUND(SUM(net_revenue), 2) FROM mart_revenue_trend"
    ).fetchone()
    assert kpis["gross_revenue"] == pytest.approx(trend[0], abs=0.01)
    assert kpis["net_revenue"] == pytest.approx(trend[1], abs=0.01)


def test_net_is_gross_plus_returns(warehouse: Connection) -> None:
    kpis = dashboard.headline_kpis(warehouse)
    assert kpis["gross_revenue"] + kpis["returns"] == pytest.approx(kpis["net_revenue"], abs=0.01)


def test_return_rate_is_a_percentage_not_a_ratio(warehouse: Connection) -> None:
    kpis = dashboard.headline_kpis(warehouse)
    expected = -kpis["returns"] / kpis["gross_revenue"] * 100
    assert kpis["return_rate_pct"] == pytest.approx(expected, abs=0.01)


def test_rfm_matrix_covers_every_scored_customer(warehouse: Connection) -> None:
    cells = dashboard.rfm_matrix(warehouse)
    total = warehouse.execute("SELECT COUNT(*) FROM mart_rfm").fetchone()[0]
    assert sum(cell["customers"] for cell in cells) == total
    assert all(1 <= cell["r_score"] <= 5 and 1 <= cell["f_score"] <= 5 for cell in cells)


def test_segment_customers_sum_to_the_rfm_mart(warehouse: Connection) -> None:
    segments = dashboard.rfm_segments(warehouse)
    total = warehouse.execute("SELECT COUNT(*) FROM mart_rfm").fetchone()[0]
    assert sum(row["customers"] for row in segments) == total


def test_pareto_curve_is_thinned_but_keeps_its_ends(warehouse: Connection) -> None:
    pareto = dashboard.pareto_curve(warehouse)
    ranks = [point["revenue_rank"] for point in pareto["curve"]]
    assert ranks[0] == 1
    assert ranks[-1] == pareto["total_skus"]
    assert ranks == sorted(ranks)
    assert pareto["curve"][-1]["cumulative_share_pct"] == pytest.approx(100.0, abs=0.01)


def test_same_day_reversals_never_exceed_total_returns(warehouse: Connection) -> None:
    reversals = dashboard.same_day_reversals(warehouse)
    returns = dashboard.headline_kpis(warehouse)["returns"]
    assert reversals["lines"] >= 0
    # both are negative, so a reversal subset can only be smaller in magnitude
    assert abs(reversals["value"] or 0.0) <= abs(returns) + 0.01


def test_payload_is_json_serialisable_and_stable(warehouse: Connection, tmp_path: Path) -> None:
    first = json.dumps(dashboard.build_payload(warehouse), indent=2, sort_keys=True)
    second = json.dumps(dashboard.build_payload(warehouse), indent=2, sort_keys=True)
    assert first == second
    target = tmp_path / "dashboard.json"
    target.write_text(first + "\n", encoding="utf-8")
    assert json.loads(target.read_text(encoding="utf-8"))["kpis"]["orders"] >= 0
