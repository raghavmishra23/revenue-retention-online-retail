DROP VIEW IF EXISTS mart_rfm;

CREATE VIEW mart_rfm AS
WITH sales_lines AS (
    -- RFM describes people, so the guest member and non-revenue lines are out
    SELECT
        f.customer_key,
        c.customer_id,
        f.invoice_no,
        f.invoice_ts,
        f.line_revenue,
        f.is_cancellation
    FROM fact_sales f
    JOIN dim_product p ON p.product_key = f.product_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    WHERE p.line_type IN ('product', 'shipping')
      AND c.is_guest = 0
),
as_of AS (
    -- the last day in the data, so recency is reproducible rather than drifting with today
    SELECT DATE(MAX(invoice_ts)) AS as_of_date
    FROM fact_sales
),
per_customer AS (
    -- frequency counts kept orders; monetary is net, so a refund pulls a customer down
    SELECT
        customer_key,
        customer_id,
        MAX(CASE WHEN is_cancellation = 0 THEN invoice_ts END) AS last_purchase_ts,
        COUNT(DISTINCT CASE WHEN is_cancellation = 0 THEN invoice_no END) AS frequency,
        SUM(line_revenue) AS monetary
    FROM sales_lines
    GROUP BY customer_key, customer_id
    HAVING last_purchase_ts IS NOT NULL
),
measured AS (
    -- whole days between the two dates; julianday is the only date arithmetic SQLite has
    SELECT
        per_customer.customer_key,
        per_customer.customer_id,
        CAST(
            julianday(as_of.as_of_date) - julianday(DATE(per_customer.last_purchase_ts)) AS INTEGER
        ) AS recency_days,
        per_customer.frequency,
        per_customer.monetary
    FROM per_customer
    CROSS JOIN as_of
),
scored AS (
    -- quintiles, with recency inverted because fewer days since the last order is better
    SELECT
        customer_key,
        customer_id,
        recency_days,
        frequency,
        monetary,
        6 - NTILE(5) OVER (ORDER BY recency_days, customer_key) AS r_score,
        NTILE(5) OVER (ORDER BY frequency, customer_key) AS f_score,
        NTILE(5) OVER (ORDER BY monetary, customer_key) AS m_score
    FROM measured
)
SELECT
    customer_key,
    customer_id,
    recency_days,
    frequency,
    monetary,
    r_score,
    f_score,
    m_score,
    r_score || f_score || m_score AS rfm_cell,
    CASE
        -- recent and frequent: the customers the business runs on
        WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
        -- still recent and ordering steadily, just short of the top quintiles
        WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal'
        -- recent but thin order history, so there is a habit still to build
        WHEN r_score >= 3 THEN 'Potential Loyalist'
        -- gone quiet after buying often and spending heavily: the costliest to lose
        WHEN f_score >= 4 AND m_score >= 4 THEN 'Cannot Lose Them'
        -- gone quiet with a real order history behind them
        WHEN f_score >= 3 THEN 'At Risk'
        -- middling lapse and little history; cheap to try to wake up
        WHEN r_score = 2 THEN 'Hibernating'
        -- longest lapse and least history, so nothing above claimed them
        ELSE 'Lost'
    END AS segment
FROM scored
ORDER BY customer_key;
