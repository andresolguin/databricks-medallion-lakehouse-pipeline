# Architecture and recovery

## Flow

`Process → immutable Staging → Bronze observations/manifest → Silver decisions → Gold → verified Archive`

The package `iowa_lakehouse` contains all business logic. Notebook entry points and CLI stages call
the same functions. Local mode addresses Delta paths; Databricks mode addresses Unity Catalog tables.

## Bronze

The delivery directory is `Process/{country}/yyyy=YYYY/mm=MM/dd=DD` under the configured volume.
Names must match `iowa_dataset_YYYYMMDD.csv`, `iowa_dataset_YYYYMMDD_part-N.csv` or
`iowa_dataset_YYYYMMDD_partNN.csv`. A directory may contain a whole file or its parts, never both.

The driver streams SHA-256 computation and stages an immutable, verified copy before Spark reads it.
The producer must deliver immutable files. The CSV reader is shared across all execution paths:
UTF-8, quoted multiline fields, string schema and `FAILFAST` for malformed CSV structure.
Semantic field errors are handled in Silver; a structurally malformed file stops ingestion.

File identity combines country, delivery date and content SHA-256. Replaying or renaming identical
contents within a delivery does not duplicate Bronze observations. The same bytes on a later delivery
are a new observation, so a legitimate later reversal of a correction is preserved.

`bronze.iowa_raw_str` stores canonical raw strings, source paths/hashes, delivery date, ingestion
timestamp/run ID, deterministic row IDs and an occurrence count for identical physical records.
`MERGE` is insert-only by row ID. `bronze.file_manifest` stores one receipt per source path/content
identity, physical record count, size, staged/archive paths and ingestion/archive status.

Raw and manifest writes are separate commits. If a failure occurs between them, replay inserts no
extra raw observations and completes the receipt. Silver rejects unregistered raw file identities
until that interrupted delivery is retried.

## Silver

The full retained Bronze history is normalized and classified. No prefix is extracted from invoice
keys. The current key is `(country, normalized invoice_line_no)`.

The latest delivery date wins for a key. Different canonical payloads on that date are rejected as a
conflict. Identical payloads select a representative deterministically by row ID. An older delivery
arriving later cannot replace a newer one. Field validation is retained for every observation,
including missing keys and superseded rows.

All dispositions are written atomically to `silver.iowa_records`:

- `CURRENT`: the unique valid current observation for a key.
- `DUPLICATE`: additional equivalent observations on the latest delivery date.
- `SUPERSEDED`: valid observations from older deliveries.
- `REJECTED`: observations failing quality or conflicting on the latest date.

Identical physical rows within a file retain their multiplicity as `occurrences`.
Accounting is `raw_rows = current_rows + duplicate_rows + superseded_rows + rejected_rows`, including
the excess occurrences of a selected CURRENT row in the duplicate total.
In Unity Catalog, clean/rejected views filter this single decision table.

An entirely invalid current snapshot stops the job after retaining rejection evidence; Gold and
source archival are untouched. There is no automatic rollback to an older version of an invalid sale.

## Gold

The full CURRENT Silver snapshot drives all dimensions and facts. `dim_time` generates a continuous
calendar from minimum to maximum valid sale date. `dim_store` and `dim_item` use natural composite
keys with Type I attributes. The latest valid sale-date observation supplies attributes; delivery
date, record hash and invoice key break ties deterministically. This is a reproducible tie-break,
not a claim that the source provides a precise attribute-change timestamp.

Dimensions merge first. The fact has a stable projection, decimal measures, actual sale-date keys,
source lineage, and year/month partitions. Its source is unique before MERGE. Changed values update
an existing key; new keys insert. `WHEN NOT MATCHED BY SOURCE DELETE` reconciles facts only because
the source is the **complete current snapshot**, never one incoming file or delivery.

This reconciliation removes a previously published sale if its latest correction is invalid.
It does not treat omission from a new delivery as deletion: older observations remain in Bronze.
Deletion events are not part of this source contract.

Publication verifies actual fact values against Silver, uniqueness, partition/date-key consistency
and dimension coverage. Errors propagate; there is no successful WARN exit.

## Archive and restart

Archive is a dependent stage after successful Gold publication. It checks that every raw observation
is in Silver and that Gold matches current Silver before moving any input out of Process.
Each staged file is copied to a hash-prefixed archive filename, content-verified, and only then are
matching source/staged copies removed. An interrupted partial archive is recopied from verified
Staging on retry. A different new file at the same source path is never removed by an older receipt.
The manifest is marked ARCHIVED last; a failure after copy/deletion is recovered from the verified
archive. Missing/corrupt copies with no verified staged source fail explicitly.

## Consistency and operational scope

Delta atomicity is per table. Silver dispositions share one commit; Gold dimensions and facts have
separate commits. Type I updates can be visible before the fact commit. Recovery is forward and
idempotent; this design does not claim a cross-table transaction or uninterrupted service during
every failure. The bundled job allows one active run. Manual writers must follow the same rule.

Silver rebuilds its complete decision snapshot and scans retained Bronze. Hashing/staging also adds
file I/O. These choices favor explicit, reproducible behavior for this project. Profile the target
volume and runtime before selecting further incremental processing, clustering or partition tuning.
