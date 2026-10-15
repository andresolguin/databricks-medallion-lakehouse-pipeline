"""Bronze -> one Silver decision snapshot -> stable Gold star schema -> Archive."""

import uuid

from pyspark.sql import Window
from pyspark.sql import functions as F

from .contracts import BUSINESS_FIELDS, classify, fingerprint
from .ingest import archive, ingest
from .storage import DeltaStore, QualityError, require_unique

KEYS = ["country", "invoice_line_no"]


def _changed(columns):
    return " OR ".join(f"NOT (t.`{column}` <=> s.`{column}`)" for column in columns)


def silver_metrics(records):
    rows = (
        records.agg(
            F.sum("occurrences").alias("raw_rows"),
            F.sum(F.when(F.col("disposition") == "CURRENT", 1).otherwise(0)).alias("current_rows"),
            F.sum(F.when(F.col("disposition") == "REJECTED", F.col("occurrences")).otherwise(0)).alias(
                "rejected_rows"
            ),
            F.sum(F.when(F.col("disposition") == "SUPERSEDED", F.col("occurrences")).otherwise(0)).alias(
                "superseded_rows"
            ),
            F.sum(
                F.when(F.col("disposition") == "DUPLICATE", F.col("occurrences"))
                .when(F.col("disposition") == "CURRENT", F.col("occurrences") - 1)
                .otherwise(0)
            ).alias("duplicate_rows"),
        )
        .first()
        .asDict()
    )
    return {key: int(value or 0) for key, value in rows.items()}


def current_sales(store):
    return store.read("silver", "iowa_records").where("disposition = 'CURRENT'")


def build_silver(store):
    if not store.exists("bronze", "iowa_raw_str"):
        raise QualityError("Bronze has not been ingested")
    raw = store.read("bronze", "iowa_raw_str")
    if not store.exists("bronze", "file_manifest"):
        raise QualityError("No committed file receipts; retry the interrupted Bronze delivery")
    registered = store.read("bronze", "file_manifest").select("source_file_id").distinct()
    if (
        raw.select("source_file_id")
        .distinct()
        .join(registered, "source_file_id", "left_anti")
        .limit(1)
        .count()
    ):
        raise QualityError("Bronze observations are awaiting a manifest; retry the interrupted delivery")
    decisions = classify(raw)
    # One Delta commit keeps accepted, rejected, duplicate and superseded dispositions consistent.
    store.write("silver", "iowa_records", decisions, mode="overwrite", partitions=("country", "disposition"))
    records = store.read("silver", "iowa_records")
    metrics = silver_metrics(records)
    if metrics["raw_rows"] != sum(
        metrics[k] for k in ("current_rows", "rejected_rows", "superseded_rows", "duplicate_rows")
    ):
        raise QualityError("Silver row accounting is incomplete")
    require_unique(records, ["row_id"], "Silver observations")
    require_unique(records.where("disposition = 'CURRENT'"), KEYS, "Silver current sales")
    if not store.config.local_root:
        target = store.name("silver", "iowa_records")
        projections = ", ".join(
            f"`{c}`"
            for c in BUSINESS_FIELDS
            + ["source_process_date", "record_hash", "source_file_id", "ingestion_ts"]
        )
        store.spark.sql(
            f"CREATE OR REPLACE VIEW {store.name('silver', 'iowa_clean_v2_strict')} AS "
            f"SELECT {projections} FROM {target} WHERE disposition = 'CURRENT'"
        )
        store.spark.sql(
            f"CREATE OR REPLACE VIEW {store.name('silver', 'iowa_rejected')} AS "
            f"SELECT * FROM {target} WHERE disposition = 'REJECTED'"
        )
    if not metrics["current_rows"]:
        raise QualityError(
            "No valid current sales; publication and archival are blocked. Inspect Silver rejections"
        )
    return metrics


def _dimension_source(sales, key, attributes):
    order = Window.partitionBy("country", key).orderBy(
        F.col("sale_date").desc(),
        F.col("source_process_date").desc(),
        F.col("record_hash").desc(),
        F.col("invoice_line_no").desc(),
    )
    columns = ["country", key] + attributes
    return (
        sales.withColumn("_rn", F.row_number().over(order))
        .where("_rn = 1")
        .select(*columns, F.col("sale_date").alias("observed_sale_date"), "source_process_date")
        .withColumn("payload_hash", fingerprint(columns + ["observed_sale_date", "source_process_date"]))
        .withColumn("updated_at", F.current_timestamp())
    )


def _assert_coverage(facts, dimension, keys, label):
    if facts.select(*keys).join(dimension.select(*keys), keys, "left_anti").limit(1).count():
        raise QualityError(f"Gold has an unmapped {label} key")


def verify_gold(store):
    """Checks read actual Delta tables; caller cannot archive an unpublished Bronze update."""
    for layer, table in [
        ("silver", "iowa_records"),
        ("gold", "fact_sales"),
        ("gold", "dim_time"),
        ("gold", "dim_store"),
        ("gold", "dim_item"),
    ]:
        if not store.exists(layer, table):
            raise QualityError(f"Missing {layer}.{table}")
    records = store.read("silver", "iowa_records")
    raw = store.read("bronze", "iowa_raw_str")
    if (
        raw.select("row_id").join(records.select("row_id"), "row_id", "left_anti").limit(1).count()
        or records.select("row_id").join(raw.select("row_id"), "row_id", "left_anti").limit(1).count()
    ):
        raise QualityError("Silver does not yet account for every Bronze observation")
    expected, actual = current_sales(store), store.read("gold", "fact_sales")
    if expected.limit(1).count() == 0:
        raise QualityError("Cannot verify an empty current snapshot")
    require_unique(actual, KEYS, "Gold fact")
    columns = KEYS + [
        "sale_date",
        "store_id",
        "item_no",
        "sale_bottles",
        "sale_dollars",
        "sale_liters",
        "sale_gallons",
        "state_bottle_cost",
        "state_bottle_retail",
        "year",
        "month",
        "source_process_date",
        "source_file_id",
        "record_hash",
    ]
    if (
        expected.select(*columns).exceptAll(actual.select(*columns)).limit(1).count()
        or actual.select(*columns).exceptAll(expected.select(*columns)).limit(1).count()
    ):
        raise QualityError("Published facts do not match the full current Silver snapshot")
    if (
        actual.where(
            "year <> year(sale_date) OR month <> month(sale_date) OR date_key <> cast(date_format(sale_date, 'yyyyMMdd') AS INT)"
        )
        .limit(1)
        .count()
    ):
        raise QualityError("Gold sale-date keys or partitions are inconsistent")
    for table, keys in [
        ("dim_time", ["date_key"]),
        ("dim_store", ["country", "store_id"]),
        ("dim_item", ["country", "item_no"]),
    ]:
        dimension = store.read("gold", table)
        require_unique(dimension, keys, table)
        _assert_coverage(actual, dimension, keys, table)
    summary = (
        actual.agg(
            F.count("*").alias("fact_rows"),
            F.sum("sale_dollars").alias("sales_usd"),
            F.min("sale_date").alias("first_sale_date"),
            F.max("sale_date").alias("last_sale_date"),
        )
        .first()
        .asDict()
    )
    return {key: str(value) if key != "fact_rows" else int(value) for key, value in summary.items()}


def publish_gold(store):
    sales = current_sales(store)
    if not sales.limit(1).count():
        raise QualityError("Cannot publish an empty current snapshot")
    require_unique(sales, KEYS, "Gold source")
    if sales.where(F.size("errors") != 0).limit(1).count():
        raise QualityError("Rejected observations reached the Gold source")

    dates = sales.agg(F.min("sale_date").alias("lo"), F.max("sale_date").alias("hi")).select(
        F.explode(F.sequence("lo", "hi", F.expr("INTERVAL 1 DAY"))).alias("date")
    )
    time = dates.select(
        F.date_format("date", "yyyyMMdd").cast("int").alias("date_key"),
        "date",
        F.year("date").alias("year"),
        F.quarter("date").alias("quarter"),
        F.month("date").alias("month"),
        F.date_format("date", "MMMM").alias("month_name"),
        F.dayofmonth("date").alias("day"),
        F.weekofyear("date").alias("week_of_year"),
        F.dayofweek("date").alias("day_of_week"),
        F.date_format("date", "EEEE").alias("day_name"),
        F.dayofweek("date").isin(1, 7).alias("is_weekend"),
    )
    store.merge("gold", "dim_time", time, ["date_key"])
    stores = _dimension_source(
        sales, "store_id", ["store_name", "address", "city", "zipcode", "county_number", "county"]
    )
    items = _dimension_source(
        sales,
        "item_no",
        ["item_desc", "pack", "bottle_volume_ml", "category_id", "category_name", "vendor_no", "vendor_name"],
    )
    for name, frame, key in [("dim_store", stores, "store_id"), ("dim_item", items, "item_no")]:
        store.merge(
            "gold",
            name,
            frame,
            ["country", key],
            update=_changed([c for c in frame.columns if c != "updated_at"]),
        )

    fact_columns = [
        "country",
        "invoice_line_no",
        "sale_date",
        "store_id",
        "item_no",
        "sale_bottles",
        "sale_dollars",
        "sale_liters",
        "sale_gallons",
        "state_bottle_cost",
        "state_bottle_retail",
        "year",
        "month",
        "source_process_date",
        "source_file_id",
        "record_hash",
    ]
    fact = (
        sales.select(*fact_columns)
        .join(time.select("date_key", F.col("date").alias("sale_date")), "sale_date")
        .withColumn("updated_at", F.current_timestamp())
    )
    require_unique(fact, KEYS, "Gold fact source")
    for table, keys in [
        ("dim_time", ["date_key"]),
        ("dim_store", ["country", "store_id"]),
        ("dim_item", ["country", "item_no"]),
    ]:
        _assert_coverage(fact, store.read("gold", table), keys, table)
    # Only one fact commit, with a stable schema, after all dimension writes and source checks.
    store.merge(
        "gold",
        "fact_sales",
        fact,
        KEYS,
        update=_changed([c for c in fact.columns if c != "updated_at"]),
        reconcile=True,
        partitions=("year", "month"),
    )
    return verify_gold(store)


def execute(spark, config, *, stage="all", run_id=None):
    store = DeltaStore(spark, config)
    run_id = run_id or uuid.uuid4().hex
    store.setup()
    stages = {
        "bronze": lambda: ingest(store, run_id),
        "silver": lambda: build_silver(store),
        "gold": lambda: publish_gold(store),
        "archive": lambda: (verify_gold(store), archive(store))[1],
    }
    if stage not in {*stages, "all"}:
        raise ValueError(f"Unknown stage: {stage}")
    selected = stages if stage == "all" else {stage: stages[stage]}
    result = {"run_id": run_id, "process_date": config.process_date}
    if stage == "all":
        result["bronze"] = stages["bronze"]()
        if result["bronze"]["already_ingested"]:
            try:
                summary = verify_gold(store)
            except QualityError:
                # E.g. Bronze committed before a prior failure in Silver or Gold.
                pass
            else:
                result.update(gold=summary, archive=archive(store), replay=True)
                return result
        selected = {name: action for name, action in stages.items() if name != "bronze"}
    for name, action in selected.items():
        result[name] = action()
    return result
