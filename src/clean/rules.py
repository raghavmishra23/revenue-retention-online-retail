"""Cleaning rules. Every rule takes a dataframe and returns a new one plus the rows it touched."""

from collections.abc import Mapping, Sequence

import pandas as pd

RAW_COLUMNS = {
    "Invoice": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_ts",
    "Price": "unit_price",
    "Customer ID": "customer_id",
    "Country": "country",
}
TEXT_COLUMNS = ("invoice_no", "stock_code", "description", "country")
LINE_TYPES = ("product", "shipping", "adjustment", "test")
DEFAULT_LINE_TYPE = "product"
CONTRACT_COLUMNS = (
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "unit_price",
    "line_revenue",
    "invoice_ts",
    "customer_id",
    "country",
    "is_cancellation",
    "line_type",
)


def normalise_columns(
    frame: pd.DataFrame, country_overrides: Mapping[str, str]
) -> tuple[pd.DataFrame, int]:
    """Rename to the snake_case contract, settle the dtypes and canonicalise the text."""
    normalised = frame.rename(columns=RAW_COLUMNS)[list(RAW_COLUMNS.values())].copy()
    # Excel hands these back as a mix of int and str, which Arrow refuses to write
    for column in TEXT_COLUMNS:
        normalised[column] = normalised[column].astype("string").str.strip()
    normalised["stock_code"] = normalised["stock_code"].str.upper()
    normalised["country"] = normalised["country"].replace(dict(country_overrides))
    normalised["quantity"] = pd.to_numeric(normalised["quantity"]).astype("int64")
    normalised["unit_price"] = pd.to_numeric(normalised["unit_price"]).astype("float64")
    normalised["customer_id"] = pd.to_numeric(normalised["customer_id"]).astype("Int64")
    normalised["invoice_ts"] = pd.to_datetime(normalised["invoice_ts"]).dt.floor("min")
    normalised["line_revenue"] = normalised["quantity"] * normalised["unit_price"]
    return normalised, len(normalised)


def backfill_description(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Fill a missing description with the most frequent one recorded for the same stock code."""
    seen = (
        frame.dropna(subset=["description"])
        .groupby(["stock_code", "description"], observed=True)
        .size()
        .reset_index(name="lines")
        # ties break on the description so the choice does not depend on row order
        .sort_values(["stock_code", "lines", "description"], ascending=[True, False, True])
    )
    modal = seen.drop_duplicates("stock_code").set_index("stock_code")["description"]

    backfilled = frame.copy()
    missing = backfilled["description"].isna()
    backfilled.loc[missing, "description"] = (
        backfilled.loc[missing, "stock_code"].map(modal).astype("string")
    )
    return backfilled, int((missing & backfilled["description"].notna()).sum())


def drop_exact_duplicates(frame: pd.DataFrame, key: Sequence[str]) -> tuple[pd.DataFrame, int]:
    deduped = frame.drop_duplicates(subset=list(key), keep="first")
    return deduped.copy(), len(frame) - len(deduped)


def flag_cancellations(frame: pd.DataFrame, prefix: str) -> tuple[pd.DataFrame, int]:
    """Cancellations stay in the facts; their negative sign is what makes net revenue honest."""
    flagged = frame.copy()
    flagged["is_cancellation"] = (
        flagged["invoice_no"].str.upper().str.startswith(prefix.upper()).fillna(False).astype(bool)
    )
    return flagged, int(flagged["is_cancellation"].sum())


def classify_line_type(
    frame: pd.DataFrame, code_groups: Mapping[str, Sequence[str]]
) -> tuple[pd.DataFrame, int]:
    """Label each line from its stock code; anything unlisted is a real product."""
    lookup = {
        str(code).strip().upper(): line_type
        for line_type, codes in code_groups.items()
        for code in codes
    }
    classified = frame.copy()
    labels = classified["stock_code"].map(lookup).fillna(DEFAULT_LINE_TYPE)
    classified["line_type"] = pd.Categorical(labels, categories=LINE_TYPES)
    return classified, int((labels != DEFAULT_LINE_TYPE).sum())


def count_guest_lines(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Guest lines keep their revenue but carry no customer, so RFM and cohorts drop them later."""
    return frame, int(frame["customer_id"].isna().sum())


def quarantine_invalid_economics(
    frame: pd.DataFrame, min_unit_price: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split off lines that cannot carry revenue, each tagged with why it was pulled."""
    reasons = pd.Series(pd.NA, index=frame.index, dtype="string")
    reasons = reasons.mask(frame["quantity"] == 0, "zero_quantity")
    reasons = reasons.mask(frame["unit_price"] <= min_unit_price, "non_positive_unit_price")

    invalid = reasons.notna()
    quarantined = frame.loc[invalid].assign(quarantine_reason=reasons.loc[invalid])
    return frame.loc[~invalid].copy(), quarantined


def reconcile(raw_rows: int, kept: int, deduped: int, quarantined: int) -> None:
    """Fail loudly: every raw row is kept, deduplicated or quarantined, never silently lost."""
    accounted = kept + deduped + quarantined
    if accounted != raw_rows:
        raise ValueError(
            f"row reconciliation failed: raw {raw_rows} != kept {kept} "
            f"+ deduped {deduped} + quarantined {quarantined} = {accounted}"
        )


def order_for_output(frame: pd.DataFrame, key: Sequence[str]) -> pd.DataFrame:
    """Deterministic row and column order so two runs write byte-identical parquet."""
    extra = [column for column in frame.columns if column not in CONTRACT_COLUMNS]
    ordered = frame.sort_values(list(key), kind="mergesort").reset_index(drop=True)
    return ordered[list(CONTRACT_COLUMNS) + extra]
