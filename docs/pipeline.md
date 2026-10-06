# Pipeline

How the data moves, what each stage promises the next one, and what fails the build.

## Flow

```text
stage       input                                  output
---------   ------------------------------------   -------------------------------------------
ingest      Kaggle slug + KAGGLE_* from env        data/raw/online_retail_II.xlsx
                                                   data/raw/checksums.json

audit       data/raw/online_retail_II.xlsx         excel/data_audit.xlsx

clean       data/raw/online_retail_II.xlsx         data/interim/raw_union.parquet
            config/settings.yml                    data/processed/transactions.parquet
                                                   data/processed/dq_report.json
                                                   data/quarantine/quarantined_rows.parquet

warehouse   data/processed/transactions.parquet    data/warehouse.sqlite
            sql/01_schema/*.sql                    data/processed/marts/*.parquet
            sql/02_marts/*.sql

dashboard   data/warehouse.sqlite                  dashboard/data/dashboard_data.js
```

`python -m src.pipeline all` runs ingest, audit, clean, warehouse, dashboard in that order. Each
stage is also a subcommand, so I can rerun one without the ones before it as long as its input is
already on disk.

## Stages

### ingest

Shells out to the Kaggle CLI in a child Python process and pulls the single file named in
`dataset.raw_filename`, not the whole dataset. Credentials come from `os.environ` after
`load_dotenv()` and are passed as child-process environment. `scrub_secrets` replaces both values
in the child's stderr before any of it is logged or raised, so a failed download cannot print a
key. A single-file Kaggle download arrives zipped even with `--unzip`, so the stage unzips any
archive left in `data/raw` and deletes it. It then writes `checksums.json` with the SHA-256, byte
size and UTC timestamp of every raw file. If the target file is already present the stage logs a
skip and returns, which is what makes repeated `all` runs cheap.

### audit

Reads both sheets of the raw workbook and writes `excel/data_audit.xlsx`: a readiness verdict
sheet, a column profile, data quality flags, revenue by month and by country with charts, and the
evidence I used to classify non-product stock codes. The first sheet records the two numbers every
later stage has to tie back to, the raw row count across both sheets and gross revenue over every
raw row. Country names are canonicalised here with the same override map the cleaning stage uses,
so the audit and the warehouse name markets identically.

### clean

`src/clean/rules.py` holds one pure function per rule; `src/clean/transactions.py` is the thin
orchestration that reads, calls them in order and writes. The order is:

1. `normalise_columns` — rename to the snake_case contract, settle dtypes, strip text, upper-case
   stock codes, apply the country overrides, floor timestamps to the minute, compute
   `line_revenue = quantity * unit_price`.
2. `backfill_description` — fill a missing description from the modal description for the same
   stock code, ties broken alphabetically.
3. `drop_exact_duplicates` — on invoice, stock code, quantity, timestamp and price.
4. `flag_cancellations` — invoice numbers starting with `C`.
5. `classify_line_type` — exact stock-code match against the shipping, adjustment and test lists;
   anything unlisted is a product.
6. `count_guest_lines` — count rows with no customer ID. Nothing is dropped.
7. `quarantine_invalid_economics` — split off rows that cannot carry revenue, each tagged with a
   reason.
8. `reconcile` — raise unless `raw == kept + deduped + quarantined`.
9. `order_for_output` — fixed row and column order so a rerun writes identical parquet.

On the current extract that reconciles as 1,067,371 raw = 1,027,015 kept + 34,337 deduped + 6,019
quarantined, every quarantined row for a non-positive unit price.

### warehouse

Builds the four dimensions and the fact in pandas, applies the DDL in `sql/01_schema` in filename
order, inserts in dependency order (`dim_date`, `dim_customer`, `dim_product`, `dim_country`,
`fact_sales`) in 50,000-row batches, then runs the integrity gates. With the tables loaded it
executes every script in `sql/02_marts`, runs the mart gates, and exports each mart view to
parquet. Mart frames are sorted on every column before writing so a rebuild produces identical
files.

### dashboard

Runs one query per panel against the mart views and writes a single payload. Shares, roll-ups and
totals are computed in SQL, so the page only formats and selects. The payload is written as
`window.DASHBOARD_DATA = {...};` rather than a `.json` file, because `fetch()` is blocked on
`file://` origins and a `.json` payload would force the dashboard to be served rather than opened.

## Data contracts

**Raw workbook to clean.** Two sheets, named `Year 2009-2010` and `Year 2010-2011`, with columns
`Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`,
`Country`.

**Clean to warehouse.** `data/processed/transactions.parquet`, one row per invoice line, columns in
this order: `invoice_no`, `stock_code`, `description`, `quantity`, `unit_price`, `line_revenue`,
`invoice_ts`, `customer_id`, `country`, `is_cancellation`, `line_type`. `line_type` is one of
`product`, `shipping`, `adjustment`, `test`. `customer_id` is nullable, and null means a guest
checkout. Quarantined rows carry the same columns plus `quarantine_reason`.

**Warehouse to marts.** The star schema documented in `docs/data_dictionary.md`. Mart views read
only `fact_sales` and the dimensions; no mart reads another mart.

**Marts to dashboard.** The six exported views, shaped by `src/dashboard/export.py` into one
payload. The page reads that payload and nothing else.

The revenue definition is the contract that matters most, and it lives in
`cleaning.net_revenue_line_types` in `config/settings.yml` so Python and SQL cannot drift apart:

- **Sales lines** are `line_type IN ('product', 'shipping')`. Adjustments and test lines are never
  revenue.
- **Gross** is sales lines excluding cancellations.
- **Returns** is sales lines that are cancellations, kept signed and therefore negative.
- **Net** is gross plus returns.
- **Return rate** is `-returns / gross`.

## The interim cache

Parsing a 1.07-million-row two-sheet workbook takes minutes, so `clean` caches the normalised union
at `data/interim/raw_union.parquet` and reuses it while it is current. Current means the cache file
is at least as new as **both** the raw workbook and `config/settings.yml`:

```python
source_mtime = max(workbook.stat().st_mtime, SETTINGS_PATH.stat().st_mtime)
if cache.exists() and cache.stat().st_mtime >= source_mtime:
    return pd.read_parquet(cache)
```

The settings file is in that comparison because normalisation bakes settings into the cached frame.
The country override map is applied at this step, so editing `United Kingdom: India` without
invalidating the cache would leave a stale country column in place, and every downstream market
number would silently disagree with the config that claims to produce it. Touching the settings
file is enough to force a re-read.

## Quality gates

Each one raises rather than letting a plausible wrong number through.

| Gate | Where | What it catches |
|---|---|---|
| `raw == kept + deduped + quarantined` | `rules.reconcile` | rows silently lost by a filter or a join |
| one line type per stock code | `build_dim_product` | a code classified two ways, which would split a SKU |
| every country has a region | `build_dim_country` | a new market arriving with no region mapping |
| no null surrogate key on `fact_sales` | `load.check_gates` | a failed dimension lookup landing as a null key |
| `PRAGMA foreign_key_check` returns nothing | `load.check_gates` | an orphan fact row; needs `foreign_keys = ON`, which the connection factory sets |
| fact row count equals source row count | `load.check_gates` | a partial or duplicated load |
| fact revenue equals source revenue to 0.01 | `load.check_gates` | a dtype or rounding change between parquet and SQLite |
| RFM scores all within 1..5 | `export._assert_rfm` | an `NTILE` inversion or an off-by-one in the recency flip |
| one row per customer in `mart_rfm` | `export._assert_rfm` | a fan-out join inflating the customer book |
| no null segment, no empty segment, no unexpected segment | `export._assert_rfm` | a hole or a typo in the `CASE` ladder |
| scored customers equal eligible customers | `export._assert_rfm` | customers quietly dropped from or added to the scoring population |
| cohort retention at offset 0 is exactly 100% | `export._assert_cohort` | a cohort assignment that does not match its own first month |
| no cohort cell with more actives than cohort size | `export._assert_cohort` | a duplicated activity row |
| Pareto cumulative share ends at 100 | `export._assert_pareto` | a window frame that does not cover the whole catalogue |
| Pareto curve never falls at a profitable SKU | `export._assert_pareto` | a broken sort order; the curve may only dip where a SKU nets negative |
| mart totals equal warehouse totals to 0.01 | `export._assert_totals` | a mart filter that disagrees with the revenue definition |
| warehouse totals equal the audited totals to 0.01 | `export._assert_totals` | any drift from the Excel baseline, in either direction |

The audited totals are pinned in `config/settings.yml` under `marts.expected_totals`: gross
20,094,028.49, returns −732,084.15, net 19,361,944.34. Those are the numbers the Excel audit and
the cleaning stage agree on, and the warehouse has to reproduce them before anything is exported.

## Idempotency

Two runs over the same raw file produce the same bytes. The pieces that make that true:

- **Ingest skips the download** when the raw file is already present, so the checksum log stays
  stable.
- **Tie-breaks are explicit.** The modal description and the modal home country both sort on the
  value after the count, so a tie never depends on row order.
- **Output order is pinned.** Cleaned rows are sorted on the duplicate key and columns are written
  in contract order. Fact rows are sorted before `sale_key` is assigned, so the same input gives
  the same surrogate keys. Mart frames are sorted on every column before export.
- **The warehouse is rebuilt, not appended.** `sql/01_schema/010_dimensions.sql` drops child-first
  so a rebuild never trips a foreign key, and each mart script drops its view before recreating it.
- **Recency is measured as of the last timestamp in the data**, not today, so RFM scores do not
  drift between runs.

## Tests

`pytest` runs with no network. The ingest tests patch `subprocess.run`. The warehouse and mart
tests build a small fixture frame, load it into a throwaway SQLite file in `tmp_path` and assert on
the gates rather than against the production database.
