# Idempotency and reconciliation

## File ingestion

Country + delivery date + content SHA-256 define a source file identity. Canonical raw strings define
the raw record hash; combining both yields a deterministic Bronze row ID. Raw MERGE only inserts
unseen IDs. Identical physical rows retain an occurrence count. A source-path/content receipt is
registered after the raw write, so a retry after an interrupted registration remains safe.

The same contents in a later delivery are a new observation: they may represent an intentional
reversal of an earlier correction. Renaming or replaying the same contents within one delivery
does not create extra current sales.

## Current sale selection

The complete invoice-line key is preserved. Latest delivery date determines precedence. A late
backfill cannot override a newer delivery. Equivalent observations deduplicate deterministically;
different canonical latest-day payloads are quarantined instead of choosing an arbitrary winner.

## Gold

The source of fact MERGE contains exactly one valid row per `(country, invoice_line_no)`.
Matching rows update only when projected values or lineage change; new keys insert. The source is
the full current Silver snapshot, so target rows absent from it can be deleted safely. An incoming
file alone must never be used with `WHEN NOT MATCHED BY SOURCE DELETE`.

Replay assertions cover fact count, sales totals and source equality. Distinct invoice counts alone
are insufficient: duplicates can also inflate revenue, volume and margin.

## Example checks in a configured Gold SQL context

```sql
SELECT country, invoice_line_no, COUNT(*) AS occurrences
FROM fact_sales
GROUP BY country, invoice_line_no
HAVING COUNT(*) <> 1;

SELECT COUNT(*) AS inconsistent_partitions
FROM fact_sales
WHERE year <> YEAR(sale_date)
   OR month <> MONTH(sale_date)
   OR date_key <> CAST(date_format(sale_date, 'yyyyMMdd') AS INT);

SELECT COUNT(*) AS unmapped_items
FROM fact_sales f
LEFT ANTI JOIN dim_item i
ON f.country = i.country AND f.item_no = i.item_no;
```

The executable pipeline raises on failed invariants before archival. The integration tests exercise
real Delta MERGE, subsequent corrections, invalid latest corrections, late backfills, partial archive
failure and recovery between raw and manifest commits.
