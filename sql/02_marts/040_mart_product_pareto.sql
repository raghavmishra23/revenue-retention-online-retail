DROP VIEW IF EXISTS mart_product_pareto;

CREATE VIEW mart_product_pareto AS
WITH product_lines AS (
    -- the catalogue curve is about goods, so shipping, adjustments and tests are out
    SELECT
        f.product_key,
        f.invoice_no,
        f.quantity,
        f.line_revenue,
        f.is_cancellation
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    WHERE p.line_type = 'product'
),
per_product AS (
    -- net revenue per SKU, so a SKU that is returned often earns its lower place
    SELECT
        product_key,
        SUM(line_revenue) AS net_revenue,
        SUM(quantity) AS units,
        COUNT(DISTINCT CASE WHEN is_cancellation = 0 THEN invoice_no END) AS orders
    FROM product_lines
    GROUP BY product_key
),
ranked AS (
    -- accumulate down the revenue order; the product key breaks ties so the curve is stable
    SELECT
        product_key,
        net_revenue,
        units,
        orders,
        ROW_NUMBER() OVER (ORDER BY net_revenue DESC, product_key) AS revenue_rank,
        100.0 * net_revenue / SUM(net_revenue) OVER () AS revenue_share_pct,
        100.0 * SUM(net_revenue) OVER (
            ORDER BY net_revenue DESC, product_key ROWS UNBOUNDED PRECEDING
        ) / SUM(net_revenue) OVER () AS cumulative_share_pct
    FROM per_product
)
SELECT
    ranked.product_key,
    p.stock_code,
    p.description,
    ranked.net_revenue,
    ranked.units,
    ranked.orders,
    ranked.revenue_rank,
    ranked.revenue_share_pct,
    ranked.cumulative_share_pct,
    -- the band is the SKUs that carry the first 80%, so the one crossing the line is in it
    CASE WHEN ranked.cumulative_share_pct - ranked.revenue_share_pct < 80.0 THEN 1 ELSE 0 END
        AS in_top_80_band
FROM ranked
JOIN dim_product p ON p.product_key = ranked.product_key
ORDER BY ranked.revenue_rank;
