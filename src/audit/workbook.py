from pathlib import Path

import pandas as pd

from src.config import get, load_settings, resolve_path
from src.utils.logging import get_logger

log = get_logger(__name__)

DUPLICATE_COLUMNS = ["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price"]
HEADER_COLOR = "#1F4E79"
BAR_COLOR = "#2E75B6"
MONEY = "#,##0.00"
COUNT = "#,##0"
PERCENT = "0.00%"


def load_raw_union() -> pd.DataFrame:
    """Read both yearly sheets once and stack them into a single frame."""
    settings = load_settings()
    source = resolve_path("raw") / get(settings, "dataset.raw_filename")
    log.info("reading %s, this takes a few minutes", source.name)
    frames = pd.read_excel(source, sheet_name=get(settings, "dataset.sheets"))
    union = pd.concat(
        [frame.assign(SourceSheet=name) for name, frame in frames.items()], ignore_index=True
    )
    # Excel hands these back as a mix of int and str, which breaks grouping and comparisons
    union["Invoice"] = union["Invoice"].astype(str)
    union["StockCode"] = union["StockCode"].astype(str)
    union["Description"] = union["Description"].astype("string")
    return union


def gross_revenue(df: pd.DataFrame) -> float:
    return float((df["Quantity"] * df["Price"]).sum())


def _with_revenue(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(Revenue=df["Quantity"] * df["Price"])


def normalised_codes(df: pd.DataFrame) -> pd.Series:
    """Stock codes as the cleaning step will see them, so this evidence matches the warehouse."""
    return df["StockCode"].str.strip().str.upper()


def stock_code_classes() -> dict[str, str]:
    cleaning = get(load_settings(), "cleaning")
    classes = {}
    for label, key in (
        ("shipping", "shipping_codes"),
        ("adjustment", "adjustment_codes"),
        ("test", "test_codes"),
    ):
        classes.update({code: label for code in cleaning[key]})
    return classes


def column_profile(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(df)
    for column in df.columns:
        series = df[column]
        numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
        nulls = int(series.isna().sum())
        rows.append(
            {
                "Column": column,
                "Dtype": str(series.dtype),
                "Non-null": total - nulls,
                "Null": nulls,
                "Null %": nulls / total if total else 0.0,
                "Distinct": int(series.nunique(dropna=True)),
                "Min": series.min() if numeric else None,
                "Max": series.max() if numeric else None,
                "Mean": series.mean() if numeric else None,
            }
        )
    return pd.DataFrame(rows)


def quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    codes = normalised_codes(df)
    is_cancellation = df["Invoice"].str.upper().str.startswith("C")
    non_product = codes.isin(stock_code_classes())
    checks = [
        (
            "Null Customer ID",
            df["Customer ID"].isna().sum(),
            "I keep these in revenue and exclude them from RFM, cohort and LTV.",
        ),
        (
            "Null Description",
            df["Description"].isna().sum(),
            "I backfill from the modal description per stock code.",
        ),
        (
            "Cancellation lines (Invoice starts with C)",
            is_cancellation.sum(),
            "I keep them, they carry the negative sign into net revenue.",
        ),
        (
            "Exact duplicates on invoice, code, quantity, timestamp, price",
            df.duplicated(subset=DUPLICATE_COLUMNS).sum(),
            "I drop them, a double-insert is the conservative read.",
        ),
        (
            "Price <= 0",
            (df["Price"] <= 0).sum(),
            "I quarantine these with a reason and never drop them silently.",
        ),
        (
            "Quantity == 0",
            (df["Quantity"] == 0).sum(),
            "The rule stays in place even though nothing hits it.",
        ),
        (
            "Negative quantity that is not a cancellation",
            ((df["Quantity"] < 0) & ~is_cancellation).sum(),
            "All of them have price 0, so the price rule already catches them.",
        ),
        (
            "Non-product stock codes (postage, adjustments, test lines)",
            non_product.sum(),
            "I classify them into shipping, adjustment and test rather than delete them.",
        ),
        (
            "Stock codes differing from their upper-case form",
            (df["StockCode"] != codes).sum(),
            "I upper-case on normalisation so 85123a and 85123A stay one SKU, not two.",
        ),
    ]
    flags = pd.DataFrame(checks, columns=["Issue", "Rows", "My decision"])
    flags["Rows"] = flags["Rows"].astype(int)
    flags.insert(2, "Share of rows", flags["Rows"] / total if total else 0.0)
    return flags


def revenue_by_month(df: pd.DataFrame) -> pd.DataFrame:
    revenue = _with_revenue(df)
    revenue["Month"] = revenue["InvoiceDate"].dt.strftime("%Y-%m")
    summary = revenue.groupby("Month").agg(Rows=("Revenue", "size"), Revenue=("Revenue", "sum"))
    return summary.reset_index().rename(columns={"Revenue": "Gross revenue"})


def revenue_by_country(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        _with_revenue(df)
        .groupby("Country")
        .agg(
            Rows=("Revenue", "size"),
            Customers=("Customer ID", "nunique"),
            Revenue=("Revenue", "sum"),
        )
        .reset_index()
        .rename(columns={"Revenue": "Gross revenue"})
    )
    return summary.sort_values("Gross revenue", ascending=False).reset_index(drop=True)


def stock_code_evidence(df: pd.DataFrame) -> pd.DataFrame:
    coded = df.assign(StockCode=normalised_codes(df))
    coded = coded[~coded["StockCode"].str.match(r"^\d")]
    classes = stock_code_classes()
    rows = []
    for code, group in _with_revenue(coded).groupby("StockCode"):
        descriptions = group["Description"].dropna().mode()
        rows.append(
            {
                "Stock code": code,
                "Class": classes.get(code, "product"),
                "Rows": len(group),
                "Total revenue": float(group["Revenue"].sum()),
                "Modal description": str(descriptions.iloc[0]) if len(descriptions) else "",
            }
        )
    evidence = pd.DataFrame(
        rows, columns=["Stock code", "Class", "Rows", "Total revenue", "Modal description"]
    )
    order = evidence["Total revenue"].abs().sort_values(ascending=False).index
    return evidence.loc[order].reset_index(drop=True)


def readiness_figures(df: pd.DataFrame) -> pd.DataFrame:
    sheet_counts = df["SourceSheet"].value_counts()
    rows = [
        (
            "Reconciliation baseline: raw rows, both sheets",
            len(df),
            "Every stage must account for all of these: kept + deduped + quarantined.",
        ),
        (
            "Reconciliation baseline: gross revenue, all raw rows",
            gross_revenue(df),
            "Quantity * Price with nothing removed. Cleaned output has to tie back to this.",
        ),
    ]
    for name in get(load_settings(), "dataset.sheets"):
        rows.append(
            (
                f"Rows in sheet {name}",
                int(sheet_counts.get(name, 0)),
                "I read each sheet as delivered and stacked them into one union.",
            )
        )
    return pd.DataFrame(rows, columns=["Figure", "Value", "My note"])


def readiness_verdict(df: pd.DataFrame) -> list[str]:
    flags = quality_flags(df).set_index("Issue")["Rows"]
    nulls = flags["Null Customer ID"]
    duplicates = flags["Exact duplicates on invoice, code, quantity, timestamp, price"]
    prices = flags["Price <= 0"]
    return [
        f"The data is usable once I deal with a few known problems: {nulls:,} rows have no "
        f"customer, {duplicates:,} rows are exact duplicates and {prices:,} rows carry a "
        "price of zero or less.",
        "I drop the duplicates, quarantine every non-positive price with a reason, and backfill "
        "missing descriptions from the modal description per stock code.",
        "I keep cancellations and anonymous rows in revenue, but exclude anonymous rows from "
        "RFM, cohort and LTV.",
        "Non-product codes such as postage and adjustments are classified, not deleted.",
        "The cleaned output has to tie back to the gross revenue and raw row count recorded "
        "above, to within 0.01.",
    ]


def _column_widths(df: pd.DataFrame, header_min: int = 10, cap: int = 70) -> list[int]:
    widths = []
    for column in df.columns:
        longest = df[column].astype(str).str.len().max() if len(df) else 0
        widths.append(min(cap, max(header_min, len(str(column)) + 4, int(longest) + 2)))
    return widths


def _write_table(
    writer: pd.ExcelWriter,
    sheet_name: str,
    df: pd.DataFrame,
    formats: dict[str, str],
    table_name: str,
):
    book = writer.book
    sheet = book.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = sheet
    header = book.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": HEADER_COLOR, "valign": "vcenter"}
    )
    columns = []
    for column in df.columns:
        spec = {"header": column, "header_format": header}
        if column in formats:
            spec["format"] = book.add_format({"num_format": formats[column]})
        columns.append(spec)
    cleaned = df.astype(object).where(df.notna(), None)
    sheet.add_table(
        0,
        0,
        len(df),
        len(df.columns) - 1,
        {
            "name": table_name,
            "data": cleaned.values.tolist(),
            "columns": columns,
            "style": "Table Style Medium 2",
        },
    )
    for index, width in enumerate(_column_widths(df)):
        sheet.set_column(index, index, width)
    sheet.freeze_panes(1, 0)
    return sheet


def _style_chart(chart, title: str, x_name: str, y_name: str) -> None:
    chart.set_title({"name": title})
    chart.set_x_axis({"name": x_name})
    chart.set_y_axis({"name": y_name, "num_format": "#,##0"})
    chart.set_legend({"none": True})


def _write_readiness(writer: pd.ExcelWriter, df: pd.DataFrame) -> None:
    book = writer.book
    sheet = book.add_worksheet("Readiness")
    writer.sheets["Readiness"] = sheet
    title = book.add_format({"bold": True, "font_size": 16, "font_color": HEADER_COLOR})
    plain = book.add_format({"text_wrap": True, "valign": "top"})
    bold = book.add_format({"bold": True})
    header = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": HEADER_COLOR})
    count = book.add_format({"num_format": COUNT, "valign": "top"})
    money = book.add_format({"num_format": MONEY, "valign": "top"})

    first, last = df["InvoiceDate"].min(), df["InvoiceDate"].max()
    sheet.write(0, 0, "Online Retail II: data readiness sign-off", title)
    sheet.write(1, 0, f"Date range covered: {first:%d %b %Y} to {last:%d %b %Y}", plain)

    figures = readiness_figures(df)
    start = 3
    sheet.add_table(
        start,
        0,
        start + len(figures),
        2,
        {
            "name": "tblReadiness",
            "columns": [{"header": c, "header_format": header} for c in figures.columns],
            "style": "Table Style Medium 2",
        },
    )
    for offset, row in enumerate(figures.itertuples(index=False), start=start + 1):
        sheet.write(offset, 0, row[0], plain)
        sheet.write_number(offset, 1, row[1], money if "revenue" in row[0] else count)
        sheet.write(offset, 2, row[2], plain)

    verdict_row = start + len(figures) + 2
    sheet.write(verdict_row, 0, "My readiness verdict", bold)
    for offset, sentence in enumerate(readiness_verdict(df), start=verdict_row + 1):
        sheet.merge_range(offset, 0, offset, 2, sentence, plain)
        sheet.set_row(offset, 32)
    sheet.set_column(0, 0, 52)
    sheet.set_column(1, 1, 20)
    sheet.set_column(2, 2, 80)
    sheet.freeze_panes(1, 0)


def build_audit_workbook(output_path: Path | None = None, raw: pd.DataFrame | None = None) -> Path:
    """Write the audit workbook; `raw` lets callers skip the slow Excel read."""
    target = output_path or resolve_path("excel_audit")
    target.parent.mkdir(parents=True, exist_ok=True)
    union = load_raw_union() if raw is None else raw

    months = revenue_by_month(union)
    countries = revenue_by_country(union)
    with pd.ExcelWriter(target, engine="xlsxwriter") as writer:
        _write_readiness(writer, union)
        _write_table(
            writer,
            "Column profile",
            column_profile(union),
            {
                "Non-null": COUNT,
                "Null": COUNT,
                "Null %": PERCENT,
                "Distinct": COUNT,
                "Min": MONEY,
                "Max": MONEY,
                "Mean": MONEY,
            },
            "tblColumnProfile",
        )
        _write_table(
            writer,
            "Data quality flags",
            quality_flags(union),
            {"Rows": COUNT, "Share of rows": PERCENT},
            "tblQualityFlags",
        )

        month_sheet = _write_table(
            writer,
            "Revenue by month",
            months,
            {"Rows": COUNT, "Gross revenue": MONEY},
            "tblRevenueByMonth",
        )
        chart = writer.book.add_chart({"type": "column"})
        chart.add_series(
            {
                "name": "Gross revenue",
                "categories": ["Revenue by month", 1, 0, len(months), 0],
                "values": ["Revenue by month", 1, 2, len(months), 2],
                "fill": {"color": BAR_COLOR},
            }
        )
        _style_chart(chart, "Gross revenue by month", "Month", "Gross revenue")
        chart.set_size({"width": 860, "height": 360})
        month_sheet.insert_chart("F2", chart)

        country_sheet = _write_table(
            writer,
            "Revenue by country",
            countries,
            {"Rows": COUNT, "Customers": COUNT, "Gross revenue": MONEY},
            "tblRevenueByCountry",
        )
        top = min(15, len(countries))
        bars = writer.book.add_chart({"type": "bar"})
        bars.add_series(
            {
                "name": "Gross revenue",
                "categories": ["Revenue by country", 1, 0, top, 0],
                "values": ["Revenue by country", 1, 3, top, 3],
                "fill": {"color": BAR_COLOR},
            }
        )
        _style_chart(bars, "Top 15 countries by gross revenue", "Country", "Gross revenue")
        # reversed so the largest country sits on top, Excel plots bar charts bottom-up
        bars.set_x_axis({"name": "Country", "reverse": True})
        bars.set_size({"width": 760, "height": 440})
        country_sheet.insert_chart("G2", bars)

        _write_table(
            writer,
            "Stock code classes",
            stock_code_evidence(union),
            {"Rows": COUNT, "Total revenue": MONEY},
            "tblStockCodeClasses",
        )
    log.info("wrote %s", target)
    return target


if __name__ == "__main__":
    print(build_audit_workbook())
