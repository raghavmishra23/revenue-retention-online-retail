-- dropped child-first so a rebuild never trips the foreign keys
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_country;

CREATE TABLE dim_date (
    date_key INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    year_month TEXT NOT NULL,
    iso_week INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    day_name TEXT NOT NULL,
    is_weekend INTEGER NOT NULL
);

CREATE TABLE dim_customer (
    customer_key INTEGER PRIMARY KEY,
    customer_id INTEGER,
    first_purchase_ts TEXT,
    last_purchase_ts TEXT,
    tenure_days INTEGER,
    home_country TEXT,
    is_guest INTEGER NOT NULL
);

CREATE TABLE dim_product (
    product_key INTEGER PRIMARY KEY,
    stock_code TEXT NOT NULL UNIQUE,
    description TEXT,
    line_type TEXT NOT NULL CHECK (line_type IN ('product', 'shipping', 'adjustment', 'test'))
);

CREATE TABLE dim_country (
    country_key INTEGER PRIMARY KEY,
    country TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL
);
