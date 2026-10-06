from pathlib import Path

import pandas as pd
import pytest

from src.config import resolve_path
from src.model.dimensions import (
    build_dim_country,
    build_dim_customer,
    build_dim_date,
    build_dim_product,
)
from src.model.facts import build_fact_sales
from src.warehouse import engine
from src.warehouse.load import load_warehouse

REGIONS = {"United Kingdom": "United Kingdom", "France": "Europe", "USA": "Americas"}
UNKNOWN_KEY = -1
SCHEMA_DIR = resolve_path("sql") / "01_schema"


def transactions_fixture() -> pd.DataFrame:
    rows = [
        ("A1", "85123A", "heart light", 6, 2.5, 15.0, "2010-12-01 08:26", 17850, "United Kingdom"),
        ("A1", "POST", "postage", 1, 18.0, 18.0, "2010-12-01 08:26", 17850, "United Kingdom"),
        ("A2", "85123A", "heart light", 2, 2.5, 5.0, "2010-12-04 10:00", None, "France"),
        ("C3", "85123A", "heart light", -1, 2.5, -2.5, "2010-12-06 09:30", 17850, "United Kingdom"),
        ("A4", "M", "manual", 1, 9.0, 9.0, "2010-12-06 11:15", 12347, "USA"),
        ("A5", "22423", "cake stand", 3, 4.0, 12.0, "2010-12-07 12:00", 12347, "USA"),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "invoice_no",
            "stock_code",
            "description",
            "quantity",
            "unit_price",
            "line_revenue",
            "invoice_ts",
            "customer_id",
            "country",
        ],
    )
    frame["invoice_ts"] = pd.to_datetime(frame["invoice_ts"])
    frame["customer_id"] = frame["customer_id"].astype("Int64")
    for column in ("invoice_no", "stock_code", "description", "country"):
        frame[column] = frame[column].astype("string")
    frame["is_cancellation"] = frame["invoice_no"].str.startswith("C").astype(bool)
    line_types = {"POST": "shipping", "M": "adjustment"}
    frame["line_type"] = pd.Categorical(frame["stock_code"].map(line_types).fillna("product"))
    return frame


def build_all(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    customers = build_dim_customer(frame, UNKNOWN_KEY)
    products = build_dim_product(frame)
    countries = build_dim_country(frame, REGIONS)
    return {
        "customers": customers,
        "products": products,
        "countries": countries,
        "fact": build_fact_sales(frame, customers, products, countries),
    }


def test_version_assert_compares_numerically() -> None:
    engine.assert_sqlite_version("3.45.1", "3.25")
    engine.assert_sqlite_version("3.25.0", "3.25")
    with pytest.raises(RuntimeError, match=r"3\.9.*3\.25"):
        engine.assert_sqlite_version("3.9", "3.25")


def test_connection_enforces_foreign_keys(tmp_path: Path) -> None:
    conn = engine.connect(tmp_path / "wh.sqlite")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_key_check_catches_an_orphan_fact(tmp_path: Path) -> None:
    conn = engine.connect(tmp_path / "wh.sqlite")
    try:
        engine.apply_schema(conn, SCHEMA_DIR)
        assert engine.foreign_key_violations(conn) == []
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO fact_sales VALUES (1, 'X', 20100101, 99, 99, 99, "
            "'2010-01-01T00:00', 1, 1.0, 1.0, 0)"
        )
        assert len(engine.foreign_key_violations(conn)) >= 1
    finally:
        conn.close()


def test_dim_date_is_a_contiguous_calendar() -> None:
    dates = build_dim_date(pd.Timestamp("2010-12-01 08:26"), pd.Timestamp("2011-01-09 17:00"))

    parsed = pd.to_datetime(dates["date"])
    assert len(dates) == 40
    assert (parsed.diff().dropna().dt.days == 1).all()
    assert dates["date_key"].is_unique

    saturday = dates[dates["date"] == "2010-12-04"].iloc[0]
    monday = dates[dates["date"] == "2010-12-06"].iloc[0]
    assert saturday["is_weekend"] == 1 and saturday["day_of_week"] == 6
    assert monday["is_weekend"] == 0 and monday["day_of_week"] == 1
    assert saturday["year_month"] == "2010-12"
    assert saturday["date_key"] == 20101204
    assert dates[dates["date"] == "2011-01-01"].iloc[0]["year_month"] == "2011-01"


def test_guests_resolve_to_the_unknown_member() -> None:
    built = build_all(transactions_fixture())
    customers, fact = built["customers"], built["fact"]

    unknown = customers[customers["customer_key"] == UNKNOWN_KEY].iloc[0]
    assert pd.isna(unknown["customer_id"]) and unknown["is_guest"] == 1
    assert (customers["is_guest"] == 0).sum() == 2

    guest_rows = fact[fact["invoice_no"] == "A2"]
    assert (guest_rows["customer_key"] == UNKNOWN_KEY).all()
    key_columns = ["date_key", "customer_key", "product_key", "country_key"]
    assert not fact[key_columns].isna().any().any()


def test_dim_product_and_country_rules() -> None:
    frame = transactions_fixture()
    products = build_dim_product(frame)
    assert products.set_index("stock_code").loc["POST", "line_type"] == "shipping"
    assert list(products["stock_code"]) == sorted(products["stock_code"])

    with pytest.raises(ValueError, match="no region"):
        build_dim_country(frame, {"France": "Europe"})


def test_surrogate_keys_are_deterministic() -> None:
    frame = transactions_fixture()
    shuffled = frame.sample(frac=1, random_state=3).reset_index(drop=True)

    first, second = build_all(frame), build_all(shuffled)

    for name in ("customers", "products", "countries", "fact"):
        pd.testing.assert_frame_equal(first[name], second[name])


def test_build_twice_leaves_identical_state(tmp_path: Path) -> None:
    frame = transactions_fixture()
    conn = engine.connect(tmp_path / "wh.sqlite")
    try:
        runs = []
        for _ in range(2):
            counts = load_warehouse(conn, frame, REGIONS, UNKNOWN_KEY, SCHEMA_DIR)
            total = conn.execute("SELECT SUM(line_revenue) FROM fact_sales").fetchone()[0]
            runs.append((counts, total))
    finally:
        conn.close()

    assert runs[0] == runs[1]
    assert runs[0][0]["fact_sales"] == len(frame)
    assert runs[0][1] == pytest.approx(frame["line_revenue"].sum())
    assert runs[0][0]["dim_customer"] == 3
