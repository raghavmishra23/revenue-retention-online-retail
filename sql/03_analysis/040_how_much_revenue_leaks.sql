-- How much revenue leaks back out as returns, and where? The five worst rows at each grain.
WITH ranked AS (
    -- most negative returns first within each grain, so one short table covers all three
    SELECT
        grain,
        grain_value,
        gross_revenue,
        returns,
        return_rate_pct,
        return_lines,
        ROW_NUMBER() OVER (PARTITION BY grain ORDER BY returns) AS leak_rank
    FROM mart_return_leakage
    WHERE gross_revenue > 0
)
SELECT
    grain,
    leak_rank,
    grain_value,
    ROUND(gross_revenue, 2) AS gross_revenue,
    ROUND(returns, 2) AS returns,
    ROUND(return_rate_pct, 2) AS return_rate_pct,
    return_lines
FROM ranked
WHERE leak_rank <= 5
ORDER BY grain, leak_rank;
