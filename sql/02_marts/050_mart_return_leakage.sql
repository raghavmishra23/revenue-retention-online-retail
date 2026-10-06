DROP VIEW IF EXISTS mart_return_leakage;

CREATE VIEW mart_return_leakage AS
WITH sales_lines AS (
    -- leakage is measured against revenue, so only product and shipping lines qualify
    SELECT
        d.year_month,
        co.country,
        pr.stock_code,
        f.line_revenue,
        f.is_cancellation
    FROM fact_sales f
    JOIN dim_product pr ON pr.product_key = f.product_key
    JOIN dim_country co ON co.country_key = f.country_key
    JOIN dim_date d ON d.date_key = f.date_key
    WHERE pr.line_type IN ('product', 'shipping')
),
by_month AS (
    -- same three sums at each grain, so the grains all reconcile to the same gross
    SELECT
        'month' AS grain,
        year_month AS grain_value,
        SUM(CASE WHEN is_cancellation = 0 THEN line_revenue ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN is_cancellation = 1 THEN line_revenue ELSE 0 END) AS returns,
        SUM(is_cancellation) AS return_lines
    FROM sales_lines
    GROUP BY year_month
),
by_country AS (
    -- where the refunds land geographically
    SELECT
        'country' AS grain,
        country AS grain_value,
        SUM(CASE WHEN is_cancellation = 0 THEN line_revenue ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN is_cancellation = 1 THEN line_revenue ELSE 0 END) AS returns,
        SUM(is_cancellation) AS return_lines
    FROM sales_lines
    GROUP BY country
),
by_product AS (
    -- which SKUs come back; shipping codes stay in so all three grains reconcile to one gross
    SELECT
        'product' AS grain,
        stock_code AS grain_value,
        SUM(CASE WHEN is_cancellation = 0 THEN line_revenue ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN is_cancellation = 1 THEN line_revenue ELSE 0 END) AS returns,
        SUM(is_cancellation) AS return_lines
    FROM sales_lines
    GROUP BY stock_code
),
stacked AS (
    -- one tidy table, so Power BI slices every grain through a single relationship
    SELECT * FROM by_month
    UNION ALL
    SELECT * FROM by_country
    UNION ALL
    SELECT * FROM by_product
)
SELECT
    grain,
    grain_value,
    gross_revenue,
    returns,
    gross_revenue + returns AS net_revenue,
    -100.0 * returns / NULLIF(gross_revenue, 0) AS return_rate_pct,
    return_lines
FROM stacked
ORDER BY grain, grain_value;
