"""Data quality metrics for the cleaned transactions, and the report they are written to."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

MONEY_DIGITS = 2
SHARE_DIGITS = 6


def _money(value: float) -> float:
    return round(float(value), MONEY_DIGITS)


def _share(part: float, whole: float) -> float:
    return round(float(part) / float(whole), SHARE_DIGITS) if whole else 0.0


def sales_lines(frame: pd.DataFrame, line_types: Sequence[str]) -> pd.DataFrame:
    """Products and shipping only, which is what counts as a sale. Adjustments and tests are out."""
    return frame.loc[frame["line_type"].isin(list(line_types))]


def gross_revenue(frame: pd.DataFrame, line_types: Sequence[str]) -> float:
    """Sales before returns, so return rate is measured against what actually went out the door."""
    sales = sales_lines(frame, line_types)
    return float(sales.loc[~sales["is_cancellation"], "line_revenue"].sum())


def returns_value(frame: pd.DataFrame, line_types: Sequence[str]) -> float:
    """Signed, so it stays negative and adds to gross rather than needing a sign flip."""
    sales = sales_lines(frame, line_types)
    return float(sales.loc[sales["is_cancellation"], "line_revenue"].sum())


def net_revenue(frame: pd.DataFrame, line_types: Sequence[str]) -> float:
    """Revenue the business actually kept: gross less what came back."""
    return float(sales_lines(frame, line_types)["line_revenue"].sum())


def line_type_breakdown(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    grouped = frame.groupby("line_type", observed=False)["line_revenue"]
    rows, revenue = grouped.size(), grouped.sum()
    return {
        str(line_type): {"rows": int(rows[line_type]), "revenue": _money(revenue[line_type])}
        for line_type in rows.index
    }


def guest_breakdown(frame: pd.DataFrame) -> dict[str, float]:
    guests = frame["customer_id"].isna()
    guest_rows = int(guests.sum())
    guest_revenue = float(frame.loc[guests, "line_revenue"].sum())
    return {
        "rows": guest_rows,
        "row_share": _share(guest_rows, len(frame)),
        "revenue": _money(guest_revenue),
        "revenue_share": _share(guest_revenue, float(frame["line_revenue"].sum())),
    }


def build_dq_report(
    kept: pd.DataFrame,
    quarantined: pd.DataFrame,
    counts: Mapping[str, int],
    rule_counts: Mapping[str, int],
    net_line_types: Sequence[str],
    raw_gross_revenue: float,
) -> dict[str, Any]:
    """Row accounting apart from rule counts, which are all measured before quarantine."""
    accounted = counts["kept_rows"] + counts["deduped_rows"] + counts["quarantined_rows"]
    gross = gross_revenue(kept, net_line_types)
    returns = returns_value(kept, net_line_types)
    return {
        "counts": dict(counts),
        "rules_before_quarantine": dict(rule_counts),
        "reconciliation": {
            "raw_rows": counts["raw_rows"],
            "accounted_rows": accounted,
            "balances": accounted == counts["raw_rows"],
        },
        "revenue": {
            "raw_gross": _money(raw_gross_revenue),
            "all_line_types": _money(kept["line_revenue"].sum()),
            "gross": _money(gross),
            "returns": _money(returns),
            "net": _money(gross + returns),
            "return_rate": _share(-returns, gross),
            "net_line_types": list(net_line_types),
        },
        "line_types": line_type_breakdown(kept),
        "guests": guest_breakdown(kept),
        "null_counts": {column: int(kept[column].isna().sum()) for column in kept.columns},
        "date_range": {
            "start": kept["invoice_ts"].min().isoformat(),
            "end": kept["invoice_ts"].max().isoformat(),
        },
        "quarantine_reasons": {
            str(reason): int(rows)
            for reason, rows in quarantined["quarantine_reason"].value_counts().items()
        },
    }


def write_dq_report(report: Mapping[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
