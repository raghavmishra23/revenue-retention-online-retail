# Data dictionary

Every table and column in the warehouse, the six marts, and the cleaned transaction grain they are
all built from. Row counts are from the current build of the 2009-12-01 to 2011-12-09 extract.

## Conventions

- **Timestamps are ISO-8601 `TEXT`.** SQLite has no date type. `invoice_ts` is `YYYY-MM-DDTHH:MM`
  and `date` is `YYYY-MM-DD`, both of which sort and compare correctly as strings. Month buckets
  come from `strftime('%Y-%m', invoice_ts)`; day arithmetic comes from `julianday()`.
- **Surrogate keys are integers**, assigned 1..n in a sorted order so a rebuild from the same rows
  produces the same keys. Natural keys (`customer_id`, `stock_code`, `country`) are kept alongside.
- **`customer_key = -1` is the unknown member**, the single row that carries every guest checkout.
  It has `is_guest = 1` and null natural key, timestamps and home country. This is what lets
  `fact_sales.customer_key` be `NOT NULL` without inventing customers.
- **Any column ending `_pct` is a percentage on a 0-100 scale**, not a 0-1 proportion. A column
  without the suffix is a count or an amount.
- **Money columns are `REAL`** and signed. A cancellation carries negative `quantity` and negative
  `line_revenue`, so sums need no sign flip.
- **Sales lines** are `line_type IN ('product', 'shipping')`. Adjustments and test lines are never
  revenue. Gross is sales lines excluding cancellations, returns is sales lines that are
  cancellations, net is their sum.

## `fact_sales`

One row per invoice line. 1,027,015 rows. Every dimension key is `NOT NULL` and enforced by a
foreign key, and `PRAGMA foreign_key_check` returns nothing after a load.

| Column | Type | Meaning |
|---|---|---|
| `sale_key` | INTEGER PK | surrogate line key, assigned after a fixed sort so rebuilds agree |
| `invoice_no` | TEXT | invoice number as delivered; a leading `C` marks a cancellation |
| `date_key` | INTEGER FK | `dim_date.date_key`, the `YYYYMMDD` of the invoice |
| `customer_key` | INTEGER FK | `dim_customer.customer_key`; `-1` for a guest checkout |
| `product_key` | INTEGER FK | `dim_product.product_key` |
| `country_key` | INTEGER FK | `dim_country.country_key`, the shipping market on the invoice |
| `invoice_ts` | TEXT | ISO-8601 to the minute, `YYYY-MM-DDTHH:MM` |
| `quantity` | INTEGER | units; negative on a cancellation |
| `unit_price` | REAL | price per unit in INR; always greater than zero after quarantine |
| `line_revenue` | REAL | `quantity * unit_price`, computed in cleaning and stored, not derived in SQL |
| `is_cancellation` | INTEGER | 1 when `invoice_no` starts with `C`, else 0 |

## `dim_date`

One row per calendar day, contiguous from 2009-12-01 to 2011-12-09. 739 rows. Built from the
observed date range, so there are no gaps even on days with no trading.

| Column | Type | Meaning |
|---|---|---|
| `date_key` | INTEGER PK | `YYYYMMDD` as an integer |
| `date` | TEXT | `YYYY-MM-DD` |
| `year` | INTEGER | calendar year |
| `quarter` | INTEGER | 1..4 |
| `month` | INTEGER | 1..12 |
| `month_name` | TEXT | full month name, e.g. `December` |
| `year_month` | TEXT | `YYYY-MM`, the month bucket every trend and cohort query groups on |
| `iso_week` | INTEGER | ISO week number, 1..53 |
| `day_of_week` | INTEGER | 1 = Monday through 7 = Sunday |
| `day_name` | TEXT | full day name, e.g. `Tuesday` |
| `is_weekend` | INTEGER | 1 for Saturday and Sunday, else 0 |

## `dim_customer`

5,940 rows: 5,939 identified customers plus the unknown member at `customer_key = -1`.

| Column | Type | Meaning |
|---|---|---|
| `customer_key` | INTEGER PK | surrogate key; `-1` is the unknown member |
| `customer_id` | INTEGER | source customer ID; null on the unknown member |
| `first_purchase_ts` | TEXT | earliest `invoice_ts` for this customer, any line type |
| `last_purchase_ts` | TEXT | latest `invoice_ts` for this customer, any line type |
| `tenure_days` | INTEGER | whole days between first and last activity |
| `home_country` | TEXT | the customer's most frequent market, ties broken alphabetically |
| `is_guest` | INTEGER | 1 on the unknown member only, else 0 |

`first_purchase_ts` and `last_purchase_ts` span every line type including cancellations, so they
describe presence in the data. RFM recency deliberately uses a narrower definition — the latest
non-cancelled sales line — and computes it in the mart rather than reading it from here.

## `dim_product`

One row per distinct stock code. 4,760 rows: 4,746 products, 3 shipping codes, 8 adjustment codes
and 3 test codes. Stock codes are upper-cased in cleaning, so a code appears exactly once.

| Column | Type | Meaning |
|---|---|---|
| `product_key` | INTEGER PK | surrogate key |
| `stock_code` | TEXT UNIQUE | upper-cased source stock code |
| `description` | TEXT | the modal description for that code, ties broken alphabetically |
| `line_type` | TEXT | `product`, `shipping`, `adjustment` or `test`; constrained by a `CHECK` |

The non-product codes: `POST`, `DOT`, `C2` are shipping; `M`, `D`, `B`, `CRUK`, `BANK CHARGES`,
`AMAZONFEE`, `ADJUST`, `ADJUST2` are adjustments; `S`, `TEST001`, `TEST002` are test lines. A load
fails if any stock code carries more than one line type.

## `dim_country`

One row per market on an invoice. 43 rows.

| Column | Type | Meaning |
|---|---|---|
| `country_key` | INTEGER PK | surrogate key |
| `country` | TEXT UNIQUE | canonical market name after the override map |
| `region` | TEXT | `India`, `Europe`, `Asia-Pacific`, `Middle East & Africa`, `Americas` or `Unspecified` |

`India` is its own region because it is the home market and 85.12% of net revenue; rolling it into a
region would hide every export market behind it. A load fails if a country has no region in
`config/settings.yml`.

## `mart_revenue_trend`

One row per calendar month with trading. 25 rows, 2009-12 to 2011-12.

| Column | Type | Meaning |
|---|---|---|
| `year_month` | TEXT | `YYYY-MM` |
| `gross_revenue` | REAL | sales lines excluding cancellations |
| `returns` | REAL | sales lines that are cancellations; negative |
| `net_revenue` | REAL | `gross_revenue + returns` |
| `orders` | INTEGER | distinct non-cancelled invoice numbers |
| `active_customers` | INTEGER | distinct identified customers with a non-cancelled sales line; guests excluded |
| `aov` | REAL | `gross_revenue / orders` |
| `return_rate_pct` | REAL | `-100 * returns / gross_revenue` |
| `net_revenue_mom_delta` | REAL | net revenue less the previous month's, from `LAG`; null in the first month |
| `net_revenue_mom_pct` | REAL | that delta as a percentage of the previous month; null in the first month |

## `mart_rfm`

One row per scoreable customer. 5,854 rows: the identified customers with at least one
non-cancelled sales line. Guests are excluded; so are the 62 customers who appear only on
adjustment or test lines and the 23 who appear only on cancellations.

| Column | Type | Meaning |
|---|---|---|
| `customer_key` | INTEGER | `dim_customer.customer_key` |
| `customer_id` | INTEGER | source customer ID |
| `recency_days` | INTEGER | whole days from the last non-cancelled sales line to the last date in the data |
| `frequency` | INTEGER | distinct non-cancelled invoices |
| `monetary` | REAL | net revenue over the customer's sales lines, so a refund pulls them down |
| `r_score` | INTEGER | recency quintile 1..5, inverted so 5 is the most recent |
| `f_score` | INTEGER | frequency quintile 1..5, 5 is the most frequent |
| `m_score` | INTEGER | monetary quintile 1..5, 5 is the highest value |
| `rfm_cell` | TEXT | the three scores concatenated, e.g. `555` |
| `segment` | TEXT | one of `Champions`, `Loyal`, `Potential Loyalist`, `At Risk`, `Cannot Lose Them`, `Hibernating`, `Lost` |

Recency is measured against the maximum `invoice_ts` in the data, not against today, so scores are
stable across runs. Quintiles come from `NTILE(5)` with `customer_key` as the tie-break, so equal
values split deterministically.

## `mart_cohort_retention`

One row per cohort and month offset at or after it. 325 rows across 25 monthly cohorts.

| Column | Type | Meaning |
|---|---|---|
| `cohort_month` | TEXT | `YYYY-MM` of the customer's first non-cancelled purchase |
| `month_offset` | INTEGER | whole months since the cohort month; 0 is the acquisition month |
| `cohort_size` | INTEGER | identified customers first seen in that month |
| `active_customers` | INTEGER | cohort members with a non-cancelled sales line in that offset month |
| `retention_pct` | REAL | `100 * active_customers / cohort_size`, rounded to 4 decimals |

The offset is computed from the year and month parts rather than from day counts, so a 31-day month
never rounds into the wrong bucket. Cells come from a month spine crossed with the cohorts
and left-joined to activity, so a month with no returning customers is a zero rather than a missing
row. `retention_pct` at offset 0 is exactly 100.0 for every cohort, and the build fails if it is
not.

## `mart_product_pareto`

One row per product SKU, ranked by net revenue. 4,746 rows. Shipping, adjustment and test codes are
excluded, because the concentration curve is about the catalogue.

| Column | Type | Meaning |
|---|---|---|
| `product_key` | INTEGER | `dim_product.product_key` |
| `stock_code` | TEXT | upper-cased stock code |
| `description` | TEXT | modal description |
| `net_revenue` | REAL | net of returns, so a heavily returned SKU earns its lower rank |
| `units` | INTEGER | net units, cancellations included as negatives |
| `orders` | INTEGER | distinct non-cancelled invoices containing the SKU |
| `revenue_rank` | INTEGER | 1 is the highest net revenue; `product_key` breaks ties |
| `revenue_share_pct` | REAL | this SKU's share of catalogue net revenue |
| `cumulative_share_pct` | REAL | running share down the rank order, ending at 100 |
| `in_top_80_band` | INTEGER | 1 if the SKU is inside the first 80% of net revenue, including the SKU that crosses the line |

## `mart_return_leakage`

Returns at three grains stacked into one table. 4,817 rows: 25 months, 43 countries and 4,749
stock codes. Shipping codes are kept in the product grain so all three grains reconcile to the same
gross.

| Column | Type | Meaning |
|---|---|---|
| `grain` | TEXT | `month`, `country` or `product` |
| `grain_value` | TEXT | the month, country or stock code this row describes |
| `gross_revenue` | REAL | sales lines excluding cancellations at this grain |
| `returns` | REAL | sales lines that are cancellations at this grain; negative |
| `net_revenue` | REAL | `gross_revenue + returns` |
| `return_rate_pct` | REAL | `-100 * returns / gross_revenue`; null where gross is zero |
| `return_lines` | INTEGER | count of cancellation lines at this grain |

## `mart_country_performance`

One row per market. 43 rows.

| Column | Type | Meaning |
|---|---|---|
| `country` | TEXT | canonical market name |
| `region` | TEXT | region from `dim_country` |
| `gross_revenue` | REAL | sales lines excluding cancellations |
| `returns` | REAL | sales lines that are cancellations; negative |
| `net_revenue` | REAL | `gross_revenue + returns` |
| `orders` | INTEGER | distinct non-cancelled invoices |
| `customers` | INTEGER | distinct identified customers; the guest member never inflates a market |
| `aov` | REAL | `gross_revenue / orders` |
| `return_rate_pct` | REAL | `-100 * returns / gross_revenue` |
| `revenue_rank` | INTEGER | `RANK()` over gross revenue descending |

## `data/processed/transactions.parquet`

The cleaned transaction grain: one row per kept invoice line, 1,027,015 rows, and the single input
the warehouse is built from. Column order is fixed by `rules.CONTRACT_COLUMNS` and row order by the
duplicate key, so two runs write identical files.

| Column | Type | Meaning |
|---|---|---|
| `invoice_no` | string | invoice number as delivered |
| `stock_code` | string | upper-cased stock code |
| `description` | string | item description, backfilled from the modal description where missing |
| `quantity` | int64 | units; negative on a cancellation |
| `unit_price` | double | price per unit in INR, always greater than zero |
| `line_revenue` | double | `quantity * unit_price` |
| `invoice_ts` | timestamp[ns] | floored to the minute |
| `customer_id` | int64, nullable | source customer ID; **null means a guest checkout** |
| `country` | string | canonical market after the override map |
| `is_cancellation` | bool | true when `invoice_no` starts with `C` |
| `line_type` | dictionary(string) | `product`, `shipping`, `adjustment` or `test` |

`data/quarantine/quarantined_rows.parquet` carries the same eleven columns plus
`quarantine_reason` (string), which is `non_positive_unit_price` for all 6,019 quarantined rows in
the current build. The rule for `zero_quantity` is in place and currently matches nothing.
