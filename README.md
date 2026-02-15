# Databricks Lakehouse Pipeline (Bronze/Silver/Gold) — Iowa Liquor Sales

End-to-end **Lakehouse** pipeline built in **Databricks** using **PySpark + Delta Lake** and **Unity Catalog**.  
Implements **Medallion Architecture (Bronze/Silver/Gold)**, strict **data quality rules**, and an analytical **Star Schema** in Gold.  
Orchestrated with Databricks **Jobs** (layer-by-layer + end-to-end orchestrator).

> Note: The original Databricks workspace used for this academy project is no longer accessible.  
> This repository contains the exported code/artifacts + full documentation so recruiters/engineers can review the work.

## What you'll find here

- Full project documentation: [docs/final_project.pdf](docs/final_project.pdf)
- Architecture diagram: [docs/diagrams/Diagrama01.png](docs/diagrams/Diagrama01.png)
- Idempotency notes + queries: [sql/idempotency/README.md](sql/idempotency/README.md)
- Business queries notebook: [sql/business_queries/4_Business_Queries.ipynb](sql/business_queries/4_Business_Queries.ipynb)
- Exported notebooks/code: [notebooks/](notebooks/)

## Tech Stack
- Databricks (Notebooks, Jobs, Volumes, Unity Catalog)
- PySpark / Spark SQL
- Delta Lake (ACID, MERGE / idempotent loads)
- Medallion Architecture

## Architecture (high level)
**Volumes (Process/Archive) → Bronze → Silver → Gold → BI/KPIs**, with an orchestrator that runs all steps end-to-end.

![Architecture Diagram](docs/diagrams/Diagrama01.png)

## Data model (Gold)
Star schema:
- `gold.dim_time` (Type I)
- `gold.dim_store` (Type I)
- `gold.dim_item` (Type I)
- `gold.fact_sales` (partitioned by `year`, `month`)

## Data quality (Silver)
`silver.iowa_clean_v2_strict` enforces rules such as:
- valid dates
- positive prices
- retail >= cost
- normalized types & ranges (pack, volume, bottles, etc.)

## Orchestration (Jobs)
- `CT_Bronze_Ingest`
- `CT_Silver_Clean`
- `CT_Gold_Publish`
- `CT_Pipeline_Orchestrator` (runs all in sequence)

## License
This repository contains my own project artifacts and documentation.  
Third‑party/course materials and datasets are **not** included here.
