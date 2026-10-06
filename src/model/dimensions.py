from collections.abc import Mapping

import pandas as pd

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M"


def _most_frequent(frame: pd.DataFrame, key: str, value: str) -> pd.Series:
    """Most common value per key; ties break alphabetically so rebuilds agree."""
    counts = frame.dropna(subset=[value]).groupby([key, value], observed=True).size()
    counts = counts.reset_index(name="rows")
    counts = counts.sort_values([key, "rows", value], ascending=[True, False, True])
    return counts.drop_duplicates(key).set_index(key)[value]


def build_dim_date(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    return pd.DataFrame(
        {
            "date_key": days.strftime("%Y%m%d").astype("int64"),
            "date": days.strftime("%Y-%m-%d"),
            "year": days.year.astype("int64"),
            "quarter": days.quarter.astype("int64"),
            "month": days.month.astype("int64"),
            "month_name": days.strftime("%B"),
            "year_month": days.strftime("%Y-%m"),
            "iso_week": days.isocalendar().week.to_numpy().astype("int64"),
            "day_of_week": (days.dayofweek + 1).astype("int64"),
            "day_name": days.strftime("%A"),
            "is_weekend": (days.dayofweek >= 5).astype("int64"),
        }
    )


def build_dim_customer(transactions: pd.DataFrame, unknown_key: int) -> pd.DataFrame:
    known = transactions.dropna(subset=["customer_id"]).copy()
    known["customer_id"] = known["customer_id"].astype("int64")
    spans = known.groupby("customer_id")["invoice_ts"].agg(["min", "max"])
    home = _most_frequent(known, "customer_id", "country")
    customers = pd.DataFrame(
        {
            "customer_id": spans.index.to_numpy(),
            "first_purchase_ts": spans["min"].dt.strftime(TIMESTAMP_FORMAT).to_numpy(),
            "last_purchase_ts": spans["max"].dt.strftime(TIMESTAMP_FORMAT).to_numpy(),
            "tenure_days": (spans["max"] - spans["min"]).dt.days.to_numpy(),
            "home_country": home.reindex(spans.index).astype(object).to_numpy(),
            "is_guest": 0,
        }
    )
    customers.insert(0, "customer_key", range(1, len(customers) + 1))
    unknown = pd.DataFrame(
        [
            {
                "customer_key": unknown_key,
                "customer_id": pd.NA,
                "first_purchase_ts": None,
                "last_purchase_ts": None,
                "tenure_days": pd.NA,
                "home_country": None,
                "is_guest": 1,
            }
        ]
    )
    combined = pd.concat([unknown, customers], ignore_index=True)
    combined["customer_id"] = combined["customer_id"].astype("Int64")
    combined["tenure_days"] = combined["tenure_days"].astype("Int64")
    return combined


def build_dim_product(transactions: pd.DataFrame) -> pd.DataFrame:
    types = transactions.groupby("stock_code")["line_type"].nunique()
    if (types > 1).any():
        raise ValueError(
            f"stock codes with more than one line type: {list(types[types > 1].index)}"
        )
    codes = pd.DataFrame({"stock_code": sorted(transactions["stock_code"].unique())})
    line_type = transactions.drop_duplicates("stock_code").set_index("stock_code")["line_type"]
    codes["description"] = codes["stock_code"].map(
        _most_frequent(transactions, "stock_code", "description")
    )
    codes["line_type"] = codes["stock_code"].map(line_type).astype(str)
    codes.insert(0, "product_key", range(1, len(codes) + 1))
    return codes


def build_dim_country(transactions: pd.DataFrame, regions: Mapping[str, str]) -> pd.DataFrame:
    countries = sorted(transactions["country"].unique())
    missing = [country for country in countries if country not in regions]
    if missing:
        raise ValueError(f"countries with no region in settings: {missing}")
    frame = pd.DataFrame({"country": countries})
    frame["region"] = frame["country"].map(regions)
    frame.insert(0, "country_key", range(1, len(frame) + 1))
    return frame
