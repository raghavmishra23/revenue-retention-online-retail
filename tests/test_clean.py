import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.clean import profile, rules

COUNTRY_OVERRIDES = {"EIRE": "Ireland", "RSA": "South Africa", "Korea": "South Korea"}
CODE_GROUPS = {
    "shipping": ["POST", "DOT", "C2"],
    "adjustment": ["M", "D", "B", "CRUK", "BANK CHARGES", "AMAZONFEE", "ADJUST", "ADJUST2"],
    "test": ["S", "TEST001", "TEST002"],
}
DUPLICATE_KEY = ["invoice_no", "stock_code", "quantity", "invoice_ts", "unit_price"]
NET_LINE_TYPES = ["product", "shipping"]


def raw_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "Invoice": 536365,
        "StockCode": "85123a",
        "Description": " white hanging heart ",
        "Quantity": 6,
        "InvoiceDate": "2010-12-01 08:26:31",
        "Price": 2.55,
        "Customer ID": 17850.0,
        "Country": "EIRE",
    }
    row.update(overrides)
    return row


def raw_frame(*rows: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=list(rules.RAW_COLUMNS))


def normalise(*rows: dict[str, Any]) -> pd.DataFrame:
    frame, _ = rules.normalise_columns(raw_frame(*rows), COUNTRY_OVERRIDES)
    return frame


def test_normalise_renames_retypes_and_canonicalises() -> None:
    frame, touched = rules.normalise_columns(
        raw_frame(raw_row(), raw_row(Country="RSA"), raw_row(Country="Unspecified")),
        COUNTRY_OVERRIDES,
    )

    assert touched == 3
    assert list(frame.columns) == list(rules.RAW_COLUMNS.values()) + ["line_revenue"]
    assert frame["stock_code"].iat[0] == "85123A"
    assert frame["description"].iat[0] == "white hanging heart"
    assert list(frame["country"]) == ["Ireland", "South Africa", "Unspecified"]
    assert frame["invoice_ts"].iat[0] == pd.Timestamp("2010-12-01 08:26:00")
    assert frame["line_revenue"].iat[0] == pytest.approx(15.3)
    assert frame["quantity"].dtype == "int64"
    assert frame["unit_price"].dtype == "float64"
    assert frame["customer_id"].dtype == "Int64"


def test_normalise_casts_the_mixed_excel_columns_to_string() -> None:
    frame, _ = rules.normalise_columns(
        raw_frame(
            raw_row(Invoice=536365, Description=12345, StockCode=22423),
            raw_row(Invoice="C536379", Description="MANUAL"),
        ),
        COUNTRY_OVERRIDES,
    )

    for column in ("invoice_no", "stock_code", "description"):
        assert frame[column].dtype == "string"
        assert all(isinstance(value, str) for value in frame[column])
    assert list(frame["invoice_no"]) == ["536365", "C536379"]
    assert frame["description"].iat[0] == "12345"


def test_normalise_keeps_a_missing_customer_null() -> None:
    frame, _ = rules.normalise_columns(
        raw_frame(raw_row(**{"Customer ID": None})), COUNTRY_OVERRIDES
    )
    assert frame["customer_id"].isna().all()


def test_backfill_description_uses_the_modal_value_per_stock_code() -> None:
    frame = normalise(
        raw_row(Description="RED LANTERN"),
        raw_row(Description="RED LANTERN"),
        raw_row(Description="red lantern typo"),
        raw_row(Description=None),
    )

    backfilled, filled = rules.backfill_description(frame)

    assert filled == 1
    assert backfilled["description"].iat[3] == "RED LANTERN"
    assert backfilled["description"].notna().all()


def test_backfill_description_leaves_a_code_with_no_description_null() -> None:
    frame = normalise(raw_row(StockCode="C3", Description=None))
    backfilled, filled = rules.backfill_description(frame)

    assert filled == 0
    assert backfilled["description"].isna().all()


def test_drop_exact_duplicates_removes_only_the_repeat() -> None:
    frame = normalise(raw_row(), raw_row(), raw_row(Quantity=7))

    deduped, dropped = rules.drop_exact_duplicates(frame, DUPLICATE_KEY)

    assert dropped == 1
    assert len(deduped) == 2
    assert sorted(deduped["quantity"]) == [6, 7]


def test_cancellations_are_kept_with_their_negative_revenue() -> None:
    frame = normalise(raw_row(), raw_row(Invoice="C536379", Quantity=-6))

    flagged, cancelled = rules.flag_cancellations(frame, "C")

    assert cancelled == 1
    assert len(flagged) == 2
    assert list(flagged["is_cancellation"]) == [False, True]
    assert flagged["line_revenue"].iat[1] == pytest.approx(-15.3)


def test_classify_line_type_labels_each_group_and_defaults_to_product() -> None:
    frame = normalise(
        raw_row(StockCode="POST"),
        raw_row(StockCode="M"),
        raw_row(StockCode="TEST001"),
        raw_row(StockCode="PADS"),
        raw_row(StockCode="SP1002"),
        raw_row(StockCode="85123a"),
    )

    classified, non_product = rules.classify_line_type(frame, CODE_GROUPS)

    assert non_product == 3
    assert list(classified["line_type"].astype(str)) == [
        "shipping",
        "adjustment",
        "test",
        "product",
        "product",
        "product",
    ]


def test_classify_line_type_matches_codes_exactly_not_by_prefix() -> None:
    frame = normalise(raw_row(StockCode="S"), raw_row(StockCode="SP1002"))
    classified, _ = rules.classify_line_type(frame, CODE_GROUPS)
    assert list(classified["line_type"].astype(str)) == ["test", "product"]


def test_count_guest_lines_counts_the_rows_with_no_customer() -> None:
    frame = normalise(raw_row(), raw_row(**{"Customer ID": None}))
    unchanged, guests = rules.count_guest_lines(frame)

    assert guests == 1
    assert unchanged.equals(frame)


def test_quarantine_pulls_non_positive_prices_with_a_reason() -> None:
    frame = normalise(raw_row(), raw_row(Price=0.0), raw_row(Price=-1.5))

    kept, quarantined = rules.quarantine_invalid_economics(frame, 0.0)

    assert len(kept) == 1
    assert kept["unit_price"].iat[0] == pytest.approx(2.55)
    assert len(quarantined) == 2
    assert set(quarantined["quarantine_reason"]) == {"non_positive_unit_price"}


def test_quarantine_pulls_zero_quantity_with_its_own_reason() -> None:
    frame = normalise(raw_row(), raw_row(Quantity=0))

    kept, quarantined = rules.quarantine_invalid_economics(frame, 0.0)

    assert len(kept) == 1
    assert list(quarantined["quarantine_reason"]) == ["zero_quantity"]


def test_reconcile_accepts_a_balanced_split() -> None:
    frame = normalise(raw_row(), raw_row(), raw_row(Price=0.0), raw_row(Quantity=9))
    deduped, dropped = rules.drop_exact_duplicates(frame, DUPLICATE_KEY)
    kept, quarantined = rules.quarantine_invalid_economics(deduped, 0.0)

    rules.reconcile(len(frame), len(kept), dropped, len(quarantined))


def test_reconcile_raises_when_rows_go_missing() -> None:
    with pytest.raises(ValueError, match="row reconciliation failed"):
        rules.reconcile(100, 90, 5, 1)


def test_order_for_output_is_stable_and_matches_the_contract() -> None:
    frame = normalise(raw_row(Quantity=9), raw_row(), raw_row(StockCode="POST"))
    frame, _ = rules.flag_cancellations(frame, "C")
    frame, _ = rules.classify_line_type(frame, CODE_GROUPS)

    ordered = rules.order_for_output(frame, DUPLICATE_KEY)

    assert list(ordered.columns) == list(rules.CONTRACT_COLUMNS)
    assert list(ordered["quantity"]) == [6, 9, 6]
    assert ordered.equals(rules.order_for_output(ordered, DUPLICATE_KEY))


def test_two_writes_of_the_same_frame_are_byte_identical(tmp_path: Path) -> None:
    frame = normalise(raw_row(), raw_row(Quantity=9), raw_row(StockCode="POST"))
    frame, _ = rules.flag_cancellations(frame, "C")
    frame, _ = rules.classify_line_type(frame, CODE_GROUPS)
    ordered = rules.order_for_output(frame, DUPLICATE_KEY)

    first, second = tmp_path / "first.parquet", tmp_path / "second.parquet"
    ordered.to_parquet(first, index=False)
    ordered.to_parquet(second, index=False)

    assert first.read_bytes() == second.read_bytes()


def test_net_revenue_excludes_adjustments_and_tests() -> None:
    frame = normalise(
        raw_row(),
        raw_row(StockCode="POST", Quantity=1, Price=18.0),
        raw_row(StockCode="M", Quantity=1, Price=100.0),
        raw_row(StockCode="TEST001", Quantity=1, Price=5.0),
    )
    classified, _ = rules.classify_line_type(frame, CODE_GROUPS)

    assert profile.net_revenue(classified, NET_LINE_TYPES) == pytest.approx(33.3)


def test_gross_is_sales_before_returns_and_net_is_gross_plus_returns() -> None:
    frame = normalise(
        raw_row(Quantity=10, Price=10.0),
        raw_row(Invoice="C536366", Quantity=-2, Price=10.0),
        raw_row(StockCode="M", Quantity=1, Price=500.0),
    )
    frame, _ = rules.flag_cancellations(frame, "C")
    classified, _ = rules.classify_line_type(frame, CODE_GROUPS)

    gross = profile.gross_revenue(classified, NET_LINE_TYPES)
    returns = profile.returns_value(classified, NET_LINE_TYPES)

    assert gross == pytest.approx(100.0)
    assert returns == pytest.approx(-20.0)
    assert gross + returns == pytest.approx(profile.net_revenue(classified, NET_LINE_TYPES))
    # the manual adjustment is big enough that it would swamp gross if it ever leaked in
    assert gross < 500.0


def test_dq_report_balances_and_writes_sorted_json(tmp_path: Path) -> None:
    frame = normalise(
        raw_row(), raw_row(), raw_row(Price=0.0), raw_row(Quantity=4, **{"Customer ID": None})
    )
    frame, _ = rules.flag_cancellations(frame, "C")
    frame, _ = rules.classify_line_type(frame, CODE_GROUPS)
    deduped, dropped = rules.drop_exact_duplicates(frame, DUPLICATE_KEY)
    kept, quarantined = rules.quarantine_invalid_economics(deduped, 0.0)

    report = profile.build_dq_report(
        kept,
        quarantined,
        {
            "raw_rows": len(frame),
            "kept_rows": len(kept),
            "deduped_rows": dropped,
            "quarantined_rows": len(quarantined),
        },
        {"descriptions_backfilled": 0, "guest_lines": 1},
        NET_LINE_TYPES,
        float(frame["line_revenue"].sum()),
    )
    path = profile.write_dq_report(report, tmp_path / "dq_report.json")
    written = path.read_bytes()

    assert report["reconciliation"]["balances"] is True
    assert report["rules_before_quarantine"]["guest_lines"] == 1
    assert report["guests"]["rows"] == 1
    assert report["quarantine_reasons"] == {"non_positive_unit_price": 1}
    assert written.endswith(b"\n")
    assert list(json.loads(written)) == sorted(json.loads(written))
