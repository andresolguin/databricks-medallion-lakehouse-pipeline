# Runbook

## Local execution

Install Java 17, Python 3.12 and `python -m pip install -e ".[local,dev]"` in a virtual environment.
The first Spark startup downloads Delta Maven artifacts unless `DELTA_JARS` points to compatible
local JARs. Set `SPARK_LOCAL_IP=127.0.0.1` if local hostname resolution is unavailable.

Generate the synthetic deliveries and run the commands in the root README. Files live under
`<local-root>/volume`; Delta tables live under `<local-root>/tables/{bronze|silver|gold}`.
Keep the same local root to test replay/corrections. Use a new root for an independent clean run.

Each stage can be run independently:

```bash
python -m iowa_lakehouse --local-root .state/demo --process-date 20251018 --stage bronze
python -m iowa_lakehouse --local-root .state/demo --process-date 20251018 --stage silver
python -m iowa_lakehouse --local-root .state/demo --process-date 20251018 --stage gold
python -m iowa_lakehouse --local-root .state/demo --process-date 20251018 --stage archive
```

The default `--stage all` executes the same sequence. Exceptions terminate with nonzero exit status.
Inspect tables with the package's `DeltaStore` or the local Spark Delta reader. Rejections are
`silver.iowa_records WHERE disposition = 'REJECTED'`; reason codes are in `errors`.

## Databricks preparation

Use a Unity Catalog workspace with Python/Spark/Delta support and an existing catalog. The bundled
serverless job uses a wheel environment; Python and Delta come from the Databricks runtime, not the
local development dependency pins. Confirm serverless/task/library support in the target workspace.

Install a current Databricks CLI, configure authentication, then validate and deploy the bundle.
For nondefault namespaces:

```bash
databricks bundle validate -t dev --var 'catalog=my_catalog,bronze_schema=iowa_bronze,silver_schema=iowa_silver,gold_schema=iowa_gold,volume=iowa_files'
databricks bundle deploy -t dev --var 'catalog=my_catalog,bronze_schema=iowa_bronze,silver_schema=iowa_silver,gold_schema=iowa_gold,volume=iowa_files'
```

Before uploading data, create the default schemas/volume (or substitute your chosen identifiers):

```sql
CREATE SCHEMA IF NOT EXISTS workspace.iowa_bronze;
CREATE SCHEMA IF NOT EXISTS workspace.iowa_silver;
CREATE SCHEMA IF NOT EXISTS workspace.iowa_gold;
CREATE VOLUME IF NOT EXISTS workspace.iowa_bronze.iowa_files;
```

The runtime identity needs USE CATALOG/SCHEMA, object creation and data/volume read/write privileges.
Use empty project schemas for a first deployment; do not point the job at unrelated existing tables.

Upload `iowa_dataset_20251018.csv` to:

`/Volumes/workspace/iowa_bronze/iowa_files/Process/usa/yyyy=2025/mm=10/dd=18/`

Upload the second delivery to its own day directory. The synthetic generator can create the files
locally for upload. Source datasets must satisfy the documented header and positive-sales contract.

```bash
databricks bundle run -t dev --params process_date=20251018 iowa_pipeline
```

The same parameters can be supplied in Jobs → Run now. `process_date` is mandatory and deliberately
has no fixed default. The job does not enable a schedule; schedule parameterization must match the
actual delivery convention before enabling automatic runs.

## Interactive notebooks

Open the repository in a Databricks Git folder on a compatible runtime, or install its built wheel
into the notebook environment. Run Bronze, Silver, Gold and Archive notebooks in that order.
Supply the same widget values for all layers. Notebook widgets do not override supplied values.
The notebooks call the same package used by the deployed job; they contain no independent load logic.

The business notebook reads published Gold. It uses Type I dimension attributes and relative calendar
windows. Set `complete_through_year` only from a confirmed source completeness watermark.

## Failed runs

1. Read the failing task's exception and source/manifest status.
2. Keep Process/Staging files; source removal only belongs to the verified archive stage.
3. Retry the interrupted delivery with the same parameters. Raw row IDs and receipts prevent replay
   duplication. Complete a failed manifest registration before publishing another delivery.
4. For field rejections/conflicts, inspect Silver `errors` and `raw_payload`. Supply a corrected
   observation with a later delivery date; do not edit the retained raw history to hide it.
5. Retry Archive after publication. A partial archive copy is verified/repaired from Staging; an
   already archived input is recognized from its manifest and content hash.

Run one writer per project namespace. A single job's concurrency setting does not serialize other
manual jobs. Gold dimensions/fact are separate Delta commits, so recovery does not imply a
cross-table rollback or a single transaction covering the whole pipeline.
