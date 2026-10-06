DROP VIEW IF EXISTS mart_revenue_trend;

CREATE VIEW mart_revenue_trend AS
WITH sales_lines AS (
    -- revenue is product and shipping only; adjustments and tests are never sales
    SELECT
        d.year_month,
        f.invoice_no,
        f.customer_key,
        c.is_guest,
        f.line_revenue,
        f.is_cancellation
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    JOIN dim_date d ON d.date_key = f.date_key
    WHERE p.line_type IN ('product', 'shipping')
),
monthly AS (
    -- gross and returns split on the cancellation flag, so net is simply their sum
    SELECT
        year_month,
        SUM(CASE WHEN is_cancellation = 0 THEN line_revenue ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN is_cancellation = 1 THEN line_revenue ELSE 0 END) AS returns,
        SUM(line_revenue) AS net_revenue,
        COUNT(DISTINCT CASE WHEN is_cancellation = 0 THEN invoice_no END) AS orders,
        COUNT(DISTINCT CASE WHEN is_cancellation = 0 AND is_guest = 0 THEN customer_key END)
            AS active_customers
    FROM sales_lines
    GROUP BY year_month
),
trend AS (
    -- LAG over the month order gives the month-on-month step without a self join
    SELECT
        year_month,
        gross_revenue,
        returns,
        net_revenue,
        orders,
        active_customers,
        gross_revenue / NULLIF(orders, 0) AS aov,
        -100.0 * returns / NULLIF(gross_revenue, 0) AS return_rate_pct,
        LAG(net_revenue) OVER (ORDER BY year_month) AS previous_net_revenue
    FROM monthly
)
SELECT
    year_month,
    gross_revenue,
    returns,
    net_revenue,
    orders,
    active_customers,
    aov,
    return_rate_pct,
    net_revenue - previous_net_revenue AS net_revenue_mom_delta,
    100.0 * (net_revenue - previous_net_revenue) / NULLIF(previous_net_revenue, 0)
        AS net_revenue_mom_pct
FROM trend
ORDER BY year_month;
