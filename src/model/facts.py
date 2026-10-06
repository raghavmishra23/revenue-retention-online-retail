import pandas as pd

from src.model.dimensions import TIMESTAMP_FORMAT

SORT_KEY = ["invoice_no", "stock_code", "invoice_ts", "quantity", "unit_price"]


def build_fact_sales(
    transactions: pd.DataFrame,
    dim_customer: pd.DataFrame,
    dim_product: pd.DataFrame,
    dim_country: pd.DataFrame,
) -> pd.DataFrame:
    # the sort pins sale_key so a rebuild from the same rows gives the same keys
    ordered = transactions.sort_values(SORT_KEY, kind="stable").reset_index(drop=True)
    guest_key = int(dim_customer.loc[dim_customer["is_guest"] == 1, "customer_key"].iloc[0])
    known_customers = dim_customer.dropna(subset=["customer_id"])
    customer_keys = pd.Series(
        known_customers["customer_key"].to_numpy(),
        index=known_customers["customer_id"].astype("int64"),
    )

    known = ordered["customer_id"].notna()
    customer_key = pd.Series(guest_key, index=ordered.index, dtype="int64")
    customer_key[known] = ordered.loc[known, "customer_id"].astype("int64").map(customer_keys)

    return pd.DataFrame(
        {
            "sale_key": range(1, len(ordered) + 1),
            "invoice_no": ordered["invoice_no"],
            "date_key": ordered["invoice_ts"].dt.strftime("%Y%m%d").astype("int64"),
            "customer_key": customer_key,
            "product_key": ordered["stock_code"].map(
                dim_product.set_index("stock_code")["product_key"]
            ),
            "country_key": ordered["country"].map(dim_country.set_index("country")["country_key"]),
            "invoice_ts": ordered["invoice_ts"].dt.strftime(TIMESTAMP_FORMAT),
            "quantity": ordered["quantity"],
            "unit_price": ordered["unit_price"],
            "line_revenue": ordered["line_revenue"],
            "is_cancellation": ordered["is_cancellation"].astype("int64"),
        }
    )
