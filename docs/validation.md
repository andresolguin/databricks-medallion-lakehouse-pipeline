# Validation

## Local environment

**Automated suite: 33 passed.**

Python 3.12 · Java 17 · Apache Spark 4.0.1 · Delta Lake 4.0.0.
Tests use genuine Delta tables in temporary local directories and entirely synthetic data.
No third-party Iowa extract is needed for the suite.

## Reproduce

```bash
python -m pip install -e ".[local,dev]"
ruff check src tests scripts examples
python scripts/check_notebooks.py
pytest -q
python -m build --wheel
```

GitHub Actions runs lint, notebook checks, the full suite and wheel packaging on pushes to main
and pull requests. Target-workspace deployment validation is a separate operation.

## Coverage

| Area | Assertions |
|---|---|
| Parameters | Real dates, safe/distinct identifiers and configured input paths |
| CSV | Multiline fields, supported header aliases, malformed structure and missing headers |
| Quality | Missing keys, invalid amounts, fractional units, extreme numbers, date/currency parsing |
| Versioning | Complete invoice keys, latest-date precedence, late backfill, equivalent duplicates, conflicts |
| Accounting | All physical occurrences classified as current, duplicate, superseded or rejected |
| Delta integration | Fresh tables, MERGE updates, replay invariance and invalid-correction reconciliation |
| Recovery | Interrupted raw/manifest registration, blocked early archive, interrupted archive copy and retry |
| Publication | Actual fact values match Silver; keys and dimension coverage are checked |
| Analytics | Exact calendar windows, same-month YoY despite gaps, explicit annual completeness, one item/month |
| Packaging | Notebook syntax/output hygiene and the serialized Databricks task chain |

## Synthetic example

The first generated delivery contains six physical records: three current facts, two rejected records
and one duplicate. Published sales total USD 270.00. Replaying the delivery preserves those values.
The second delivery corrects an existing sale and adds another: four facts, USD 366.00.
The integration scenario also checks a late backfill, a later invalid correction and a legitimate
later delivery whose contents match an earlier file.

## Scope of the evidence

These checks establish local behavior on the declared runtime and fixtures. They do not establish
throughput on millions of records, cloud service reliability, Unity Catalog permissions or execution
in an unavailable Databricks workspace. Validate the bundle and run the job in the target workspace
before treating that environment as verified. The source data contract and quality tolerances must
also be checked against the chosen real extract.

Silver is a full reconciliation of retained observations. Delta atomicity is per table and does not
provide a multi-table Gold transaction. Those are explicit design properties, not performance or
transaction guarantees inferred from passing tests.

## Rebuild the technical overview

```bash
python -m pip install -e ".[docs]"
python scripts/render_docs.py
```

This renders the architecture PNG/SVG and `docs/final_project.pdf` from the documented project model.
