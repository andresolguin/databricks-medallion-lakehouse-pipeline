# Data contract

## Source identity and scope

- Domain: Iowa Liquor Sales historical invoice-line export.
- Accepted raw header aliases: see `RAW_ALIASES` in `src/iowa_lakehouse/contracts.py`.
- Required headers: invoice key, date, store/item numbers, pack, bottle volume, cost/retail,
  bottles, dollars, liters and gallons. Optional descriptive headers default to NULL.
- Required nonempty logical identifiers: `country`, full normalized invoice-line key, positive
  integer `store_id` and `item_no`. Invoice identifiers are opaque, uppercased and trimmed;
  letters, digits, hyphens and underscores are accepted. No numeric-prefix grouping is performed.
- Delivery files are immutable. Corrections use a later delivery date. Different latest-day
  payloads for the same logical key are quarantined as a conflict.

## Types and quality

| Field | Type/rule |
|---|---|
| `sale_date` | Valid DATE from ISO date/timestamp or M/d/yyyy |
| `store_id`, `item_no` | Positive INT |
| `pack`, `bottle_volume_ml`, `sale_bottles` | Positive whole INT; fractional values and overflow reject |
| `state_bottle_cost`, `state_bottle_retail` | Positive DECIMAL(12,2); retail >= cost |
| `sale_dollars` | Positive DECIMAL(14,2) |
| `sale_liters`, `sale_gallons` | Positive DECIMAL(14,3) |
| `zipcode` | STRING, retaining leading zeros |
| `county_number`, `category_id`, `vendor_no` | Nullable INT descriptive attributes |
| `year`, `month` | Derived from sale_date, not ingestion/delivery date |

Currency symbols and thousands separators are removed before tolerant casts. Money is normalized
to cents and volumes to three decimals. Optional descriptive values may be unknown; their original
raw strings remain in Bronze and `raw_payload` in Silver.

The positive-sales scope excludes returns and reversals. There are no inferred maximum pack sizes,
bottle sizes or order quantities. Per-record balance checks use:

- `abs(sale_dollars - sale_bottles * state_bottle_retail) <= USD 0.05`.
- `abs(sale_liters - bottle_volume_ml * sale_bottles / 1000) <= 0.02 L`.
- `abs(sale_gallons - sale_liters / 3.785411784) <= 0.02 US gal`.

These are project acceptance tolerances, not claims about all records published by the provider.
Validate them against an identified source extract before a larger run.

## Rejections and lineage

Each rejected observation retains all applicable reason codes, raw JSON payload, source file ID,
SHA-256, path/name, delivery date, ingestion run/timestamp, row ID and occurrence count. A malformed
CSV structure fails the entire file before registration; its source/staged files remain available.
Repeated physical rows are counted, not silently discarded. Silver accounting covers every retained
Bronze observation and occurrence.

## Gold keys and schema

`dim_time`: `date_key INT yyyyMMdd`, date, year, quarter, month, month_name, day, week_of_year,
day_of_week (1=Sunday, 7=Saturday), day_name, is_weekend.

`dim_store`: `(country STRING, store_id INT)`, store_name, address, city, zipcode, county_number,
county, observed_sale_date, source_process_date, payload_hash, updated_at.

`dim_item`: `(country STRING, item_no INT)`, item_desc, pack, bottle_volume_ml, category_id,
category_name, vendor_no, vendor_name, observed_sale_date, source_process_date, payload_hash, updated_at.

`fact_sales`: `(country STRING, invoice_line_no STRING)`, sale_date, date_key, store_id, item_no,
sale_bottles, sale_dollars, sale_liters, sale_gallons, state_bottle_cost, state_bottle_retail, year,
month, source_process_date, source_file_id, record_hash, updated_at.
Partition columns are `year, month`; logical keys and foreign-key coverage are checked by the job.

Type I dimension joins apply current attributes to historical sales. Source columns do not provide
the effective periods required to promise a historical Type II attribution model.
