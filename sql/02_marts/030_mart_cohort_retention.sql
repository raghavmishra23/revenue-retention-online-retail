DROP VIEW IF EXISTS mart_cohort_retention;

CREATE VIEW mart_cohort_retention AS
WITH purchases AS (
    -- retention counts kept orders by real customers; a cancellation is not activity
    SELECT DISTINCT
        f.customer_key,
        d.year_month AS activity_month
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    JOIN dim_date d ON d.date_key = f.date_key
    WHERE p.line_type IN ('product', 'shipping')
      AND c.is_guest = 0
      AND f.is_cancellation = 0
),
cohorts AS (
    -- a customer belongs to the month of their first purchase and never moves
    SELECT
        customer_key,
        MIN(activity_month) AS cohort_month
    FROM purchases
    GROUP BY customer_key
),
cohort_sizes AS (
    -- the denominator of every retention percentage for that cohort
    SELECT
        cohort_month,
        COUNT(*) AS cohort_size
    FROM cohorts
    GROUP BY cohort_month
),
active AS (
    -- offset in whole months from the year and month parts; dividing days would drift
    SELECT
        c.cohort_month,
        (CAST(substr(p.activity_month, 1, 4) AS INTEGER)
            - CAST(substr(c.cohort_month, 1, 4) AS INTEGER)) * 12
        + (CAST(substr(p.activity_month, 6, 2) AS INTEGER)
            - CAST(substr(c.cohort_month, 6, 2) AS INTEGER)) AS month_offset,
        COUNT(DISTINCT p.customer_key) AS active_customers
    FROM purchases p
    JOIN cohorts c ON c.customer_key = p.customer_key
    GROUP BY 1, 2
),
month_spine AS (
    -- every calendar month in the warehouse, so a dead month shows as a zero not a gap
    SELECT DISTINCT year_month
    FROM dim_date
),
cells AS (
    -- one row per cohort and every month at or after it; SQLite has no FULL OUTER JOIN
    SELECT
        s.cohort_month,
        s.cohort_size,
        (CAST(substr(m.year_month, 1, 4) AS INTEGER)
            - CAST(substr(s.cohort_month, 1, 4) AS INTEGER)) * 12
        + (CAST(substr(m.year_month, 6, 2) AS INTEGER)
            - CAST(substr(s.cohort_month, 6, 2) AS INTEGER)) AS month_offset
    FROM cohort_sizes s
    CROSS JOIN month_spine m
    WHERE m.year_month >= s.cohort_month
)
SELECT
    cells.cohort_month,
    cells.month_offset,
    cells.cohort_size,
    COALESCE(active.active_customers, 0) AS active_customers,
    ROUND(100.0 * COALESCE(active.active_customers, 0) / cells.cohort_size, 4) AS retention_pct
FROM cells
LEFT JOIN active
    ON active.cohort_month = cells.cohort_month
   AND active.month_offset = cells.month_offset
ORDER BY cells.cohort_month, cells.month_offset;
