-- Which products carry the revenue? How concentrated the catalogue is either side of the 80% line.
SELECT
    CASE WHEN in_top_80_band = 1 THEN 'first 80% of revenue' ELSE 'the long tail' END AS band,
    COUNT(*) AS skus,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_skus,
    SUM(units) AS units,
    ROUND(SUM(net_revenue), 2) AS net_revenue,
    ROUND(100.0 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2) AS pct_of_net_revenue,
    ROUND(AVG(net_revenue), 2) AS avg_net_revenue_per_sku
FROM mart_product_pareto
GROUP BY in_top_80_band
ORDER BY in_top_80_band DESC;
