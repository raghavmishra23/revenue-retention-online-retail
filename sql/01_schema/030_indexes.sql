CREATE INDEX idx_fact_sales_date ON fact_sales (date_key);
CREATE INDEX idx_fact_sales_customer_date ON fact_sales (customer_key, date_key);
CREATE INDEX idx_fact_sales_product ON fact_sales (product_key);
CREATE INDEX idx_fact_sales_country ON fact_sales (country_key);
