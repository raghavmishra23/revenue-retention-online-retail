import pandas as pd
import pytest

from src.audit import workbook
from src.audit.workbook import (
    build_audit_workbook,
    column_profile,
    quality_flags,
    revenue_by_country,
    revenue_by_month,
    stock_code_evidence,
)

SHEETS = [
    "Readiness",
    "Column profile",
    "Data quality flags",
    "Revenue by month",
    "Revenue by country",
    "Stock code classes",
]


@pytest.fixture
def raw_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Invoice": ["1001", "1001", "1001", "C1002", "1003", "1004", "1005"],
            "StockCode": ["85123A", "85123A", "POST", "22423", "TEST", "22423", "M"],
            "Description": ["MUG", "MUG", "POSTAGE", None, "test item", "CAKE STAND", "Manual"],
            "Quantity": [2, 2, 1, -1, 5, -3, 1],
            "InvoiceDate": pd.to_datetime(
                [
                    "2010-12-30 09:00",
                    "2010-12-30 09:00",
                    "2010-12-31 10:00",
                    "2011-01-02 11:00",
                    "2011-01-03 12:00",
                    "2011-01-04 13:00",
                    "2011-01-05 14:00",
                ]
            ),
            "Price": [3.0, 3.0, 18.0, 10.0, 0.0, 0.0, 5.0],
            "Customer ID": [1.0, 1.0, None, 2.0, None, 3.0, 2.0],
            "Country": ["United Kingdom"] * 3 + ["France", "France", "Germany", "France"],
            "SourceSheet": ["Year 2009-2010"] * 3 + ["Year 2010-2011"] * 4,
        }
    )


def test_column_profile_counts_nulls_and_distincts(raw_rows):
    profile = column_profile(raw_rows).set_index("Column")
    assert profile.loc["Customer ID", "Null"] == 2
    assert profile.loc["Customer ID", "Non-null"] == 5
    assert profile.loc["Customer ID", "Distinct"] == 3
    assert profile.loc["Description", "Null"] == 1
    assert profile.loc["Quantity", "Min"] == -3
    assert pd.isna(profile.loc["Country", "Mean"])


def test_revenue_by_month_crosses_year_boundary(raw_rows):
    months = revenue_by_month(raw_rows).set_index("Month")
    assert list(months.index) == ["2010-12", "2011-01"]
    assert months.loc["2010-12", "Rows"] == 3
    assert months.loc["2010-12", "Gross revenue"] == pytest.approx(30.0)
    assert months.loc["2011-01", "Gross revenue"] == pytest.approx(-10.0 + 0 + 0 + 5.0)


def test_revenue_by_country_aggregates_and_sorts(raw_rows):
    countries = revenue_by_country(raw_rows)
    assert list(countries["Country"]) == ["United Kingdom", "Germany", "France"]
    assert list(countries["Gross revenue"]) == pytest.approx([30.0, 0.0, -5.0])
    france = countries.set_index("Country").loc["France"]
    assert france["Rows"] == 3
    assert france["Customers"] == 1


def test_quality_flags_counts(raw_rows):
    flags = quality_flags(raw_rows).set_index("Issue")["Rows"]
    assert flags["Null Customer ID"] == 2
    assert flags["Exact duplicates on invoice, code, quantity, timestamp, price"] == 1
    assert flags["Price <= 0"] == 2
    assert flags["Cancellation lines (Invoice starts with C)"] == 1
    assert flags["Negative quantity that is not a cancellation"] == 1
    assert flags["Quantity == 0"] == 0


def test_stock_code_evidence_sorted_by_absolute_revenue(raw_rows):
    evidence = stock_code_evidence(raw_rows)
    assert list(evidence["Stock code"]) == ["POST", "M", "TEST"]
    assert evidence.set_index("Stock code").loc["POST", "Class"] == "shipping"


def test_build_audit_workbook_writes_expected_sheets(raw_rows, tmp_path):
    target = build_audit_workbook(tmp_path / "audit.xlsx", raw=raw_rows)
    assert target.exists()
    assert pd.ExcelFile(target).sheet_names == SHEETS


def test_build_audit_workbook_does_not_read_source_when_injected(raw_rows, tmp_path, monkeypatch):
    def fail() -> pd.DataFrame:
        raise AssertionError("raw workbook should not be read")

    monkeypatch.setattr(workbook, "load_raw_union", fail)
    build_audit_workbook(tmp_path / "audit.xlsx", raw=raw_rows)
