-- Where does the revenue come from? The ten largest markets and what each contributes.
SELECT
    revenue_rank,
    country,
    region,
    ROUND(gross_revenue, 2) AS gross_revenue,
    ROUND(returns, 2) AS returns,
    ROUND(net_revenue, 2) AS net_revenue,
    ROUND(100.0 * net_revenue / SUM(net_revenue) OVER (), 2) AS pct_of_net_revenue,
    orders,
    customers,
    ROUND(aov, 2) AS aov,
    ROUND(return_rate_pct, 2) AS return_rate_pct
FROM mart_country_performance
ORDER BY revenue_rank
LIMIT 10;
