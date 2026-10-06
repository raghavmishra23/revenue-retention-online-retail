-- Which customers should I spend retention money on? Every RFM segment, sized and valued.
SELECT
    segment,
    COUNT(*) AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_customers,
    ROUND(SUM(monetary), 2) AS net_revenue,
    ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 2) AS pct_of_net_revenue,
    ROUND(AVG(recency_days), 1) AS avg_days_since_order,
    ROUND(AVG(frequency), 1) AS avg_orders,
    ROUND(AVG(monetary), 2) AS avg_net_revenue
FROM mart_rfm
GROUP BY segment
ORDER BY net_revenue DESC;
