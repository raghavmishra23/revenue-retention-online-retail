DROP VIEW IF EXISTS mart_country_performance;

CREATE VIEW mart_country_performance AS
WITH sales_lines AS (
    -- the market view uses the same revenue definition as every other mart
    SELECT
        co.country,
        co.region,
        f.invoice_no,
        f.customer_key,
        c.is_guest,
        f.line_revenue,
        f.is_cancellation
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    JOIN dim_country co ON co.country_key = f.country_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    WHERE p.line_type IN ('product', 'shipping')
),
per_country AS (
    -- customers counts real people only, so the guest member never inflates a market
    SELECT
        country,
        region,
        SUM(CASE WHEN is_cancellation = 0 THEN line_revenue ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN is_cancellation = 1 THEN line_revenue ELSE 0 END) AS returns,
        SUM(line_revenue) AS net_revenue,
        COUNT(DISTINCT CASE WHEN is_cancellation = 0 THEN invoice_no END) AS orders,
        COUNT(DISTINCT CASE WHEN is_guest = 0 THEN customer_key END) AS customers
    FROM sales_lines
    GROUP BY country, region
)
SELECT
    country,
    region,
    gross_revenue,
    returns,
    net_revenue,
    orders,
    customers,
    gross_revenue / NULLIF(orders, 0) AS aov,
    -100.0 * returns / NULLIF(gross_revenue, 0) AS return_rate_pct,
    RANK() OVER (ORDER BY gross_revenue DESC) AS revenue_rank
FROM per_country
ORDER BY revenue_rank;
