CREATE TABLE fact_sales (
    sale_key INTEGER PRIMARY KEY,
    invoice_no TEXT NOT NULL,
    date_key INTEGER NOT NULL REFERENCES dim_date (date_key),
    customer_key INTEGER NOT NULL REFERENCES dim_customer (customer_key),
    product_key INTEGER NOT NULL REFERENCES dim_product (product_key),
    country_key INTEGER NOT NULL REFERENCES dim_country (country_key),
    invoice_ts TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    line_revenue REAL NOT NULL,
    is_cancellation INTEGER NOT NULL
);
