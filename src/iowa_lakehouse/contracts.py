"""Explicit typing, quality reasons and deterministic current-record selection."""

from pyspark.sql import Window
from pyspark.sql import functions as F

RAW_ALIASES = {
    "invoice_line_no": ("invoice_line_no", "Invoice/Item Number"),
    "date": ("date", "Date"),
    "store": ("store", "Store Number"),
    "name": ("name", "Store Name"),
    "address": ("address", "Address"),
    "city": ("city", "City"),
    "zipcode": ("zipcode", "Zip Code"),
    "store_location": ("store_location", "Store Location"),
    "county_number": ("county_number", "County Number"),
    "county": ("county", "County"),
    "category": ("category", "Category"),
    "category_name": ("category_name", "Category Name"),
    "vendor_no": ("vendor_no", "Vendor Number"),
    "vendor_name": ("vendor_name", "Vendor Name"),
    "itemno": ("itemno", "Item Number"),
    "im_desc": ("im_desc", "Item Description"),
    "pack": ("pack", "Pack"),
    "bottle_volume_ml": ("bottle_volume_ml", "Bottle Volume (ml)"),
    "state_bottle_cost": ("state_bottle_cost", "State Bottle Cost"),
    "state_bottle_retail": ("state_bottle_retail", "State Bottle Retail"),
    "sale_bottles": ("sale_bottles", "Bottles Sold"),
    "sale_dollars": ("sale_dollars", "Sale (Dollars)"),
    "sale_liters": ("sale_liters", "Volume Sold (Liters)"),
    "sale_gallons": ("sale_gallons", "Volume Sold (Gallons)"),
}
RAW_FIELDS = list(RAW_ALIASES)
REQUIRED_HEADERS = {
    "invoice_line_no",
    "date",
    "store",
    "itemno",
    "pack",
    "bottle_volume_ml",
    "state_bottle_cost",
    "state_bottle_retail",
    "sale_bottles",
    "sale_dollars",
    "sale_liters",
    "sale_gallons",
}
BUSINESS_FIELDS = [
    "country",
    "invoice_line_no",
    "sale_date",
    "store_id",
    "store_name",
    "address",
    "city",
    "zipcode",
    "county_number",
    "county",
    "item_no",
    "item_desc",
    "category_id",
    "category_name",
    "vendor_no",
    "vendor_name",
    "pack",
    "bottle_volume_ml",
    "state_bottle_cost",
    "state_bottle_retail",
    "sale_bottles",
    "sale_dollars",
    "sale_liters",
    "sale_gallons",
    "year",
    "month",
]


def fingerprint(columns):
    return F.sha2(F.to_json(F.struct(*[F.col(c) for c in columns]), {"ignoreNullFields": "false"}), 256)


def _text(column):
    return F.when(F.trim(F.col(column)) != "", F.trim(F.col(column)))


def _number(column, dtype):
    return F.expr(f"try_cast(nullif(regexp_replace(trim(`{column}`), '[$,]', ''), '') AS {dtype})")


def normalize(raw):
    """All casts are tolerant; validation sees the resulting NULL rather than dropping the row."""
    sale_date = F.coalesce(
        F.expr("try_cast(substring(`date`, 1, 10) AS DATE)"),
        F.try_to_timestamp(F.col("date"), F.lit("M/d/yyyy")).cast("date"),
    )
    typed = raw.select(
        "row_id",
        "source_file_id",
        "source_sha256",
        "source_path",
        "source_file_name",
        "source_process_date",
        "ingestion_ts",
        "ingestion_run_id",
        "occurrences",
        "country",
        F.to_json(F.struct(*RAW_FIELDS), {"ignoreNullFields": "false"}).alias("raw_payload"),
        F.upper(_text("invoice_line_no")).alias("invoice_line_no"),
        sale_date.alias("sale_date"),
        _number("store", "INT").alias("store_id"),
        _text("name").alias("store_name"),
        *[
            _text(c).alias(c)
            for c in ("address", "city", "zipcode", "county", "category_name", "vendor_name")
        ],
        _number("county_number", "INT").alias("county_number"),
        _number("itemno", "INT").alias("item_no"),
        _text("im_desc").alias("item_desc"),
        _number("category", "INT").alias("category_id"),
        _number("vendor_no", "INT").alias("vendor_no"),
        *[
            _number(c, "DECIMAL(20,6)").alias(f"_{c}_number")
            for c in ("pack", "bottle_volume_ml", "sale_bottles")
        ],
        *[_number(c, "DECIMAL(12,2)").alias(c) for c in ("state_bottle_cost", "state_bottle_retail")],
        _number("sale_dollars", "DECIMAL(14,2)").alias("sale_dollars"),
        *[_number(c, "DECIMAL(14,3)").alias(c) for c in ("sale_liters", "sale_gallons")],
    )
    for column in ("pack", "bottle_volume_ml", "sale_bottles"):
        typed = typed.withColumn(column, F.expr(f"try_cast(`_{column}_number` AS INT)"))
    typed = typed.withColumn("year", F.year("sale_date")).withColumn("month", F.month("sale_date"))

    rules = [
        (
            F.col("invoice_line_no").isNull() | ~F.col("invoice_line_no").rlike(r"^[A-Z0-9][A-Z0-9_-]*$"),
            "INVALID_INVOICE_KEY",
        ),
        (F.col("sale_date").isNull(), "INVALID_SALE_DATE"),
        (F.col("store_id").isNull() | (F.col("store_id") <= 0), "INVALID_STORE_ID"),
        (F.col("item_no").isNull() | (F.col("item_no") <= 0), "INVALID_ITEM_NO"),
    ]
    for column in ("pack", "bottle_volume_ml", "sale_bottles"):
        rules.append(
            (
                F.col(column).isNull() | (F.col(column) <= 0) | (F.col(f"_{column}_number") != F.col(column)),
                f"INVALID_{column.upper()}",
            )
        )
    for column in ("state_bottle_cost", "state_bottle_retail", "sale_dollars", "sale_liters", "sale_gallons"):
        rules.append((F.col(column).isNull() | (F.col(column) <= 0), f"INVALID_{column.upper()}"))
    rules.extend(
        [
            (F.col("state_bottle_retail") < F.col("state_bottle_cost"), "RETAIL_BELOW_COST"),
            (
                F.abs(F.col("sale_dollars") - F.col("state_bottle_retail") * F.col("sale_bottles"))
                > F.lit("0.05").cast("decimal(14,2)"),
                "REVENUE_MISMATCH",
            ),
            (
                F.abs(
                    F.col("sale_liters")
                    - F.col("bottle_volume_ml").cast("decimal(20,3)")
                    * F.col("sale_bottles").cast("decimal(20,3)")
                    / 1000
                )
                > F.lit(0.02),
                "LITERS_MISMATCH",
            ),
            (
                F.abs(F.col("sale_gallons") - F.col("sale_liters") / F.lit(3.785411784)) > F.lit(0.02),
                "GALLONS_MISMATCH",
            ),
        ]
    )
    errors = F.filter(
        F.array(*[F.when(F.coalesce(condition, F.lit(False)), reason) for condition, reason in rules]),
        lambda x: x.isNotNull(),
    )
    return (
        typed.withColumn("errors", errors)
        .withColumn("record_hash", fingerprint(BUSINESS_FIELDS))
        .drop(*[f"_{c}_number" for c in ("pack", "bottle_volume_ml", "sale_bottles")])
    )


def classify(raw):
    """Latest delivery wins; conflicting payloads on that date are quarantined as a group.

    Validation occurs after version selection: a later invalid correction cannot
    silently resurrect an older sale. Missing keys remain individually auditable.
    """
    typed = normalize(raw)
    keys = ["country", "invoice_line_no"]
    latest = typed.groupBy(*keys).agg(F.max("source_process_date").alias("_latest_date"))
    candidates = typed.join(latest, keys, "left")
    variants = (
        candidates.where("source_process_date = _latest_date")
        .groupBy(*keys)
        .agg(F.countDistinct("record_hash").alias("_variants"))
    )
    ranked = candidates.join(variants, keys, "left")
    latest_day = F.col("source_process_date") == F.col("_latest_date")
    conflict = latest_day & (F.col("_variants") > 1)
    ranked = ranked.withColumn(
        "errors",
        F.when(conflict, F.array_union("errors", F.array(F.lit("CONFLICTING_LATEST_RECORDS")))).otherwise(
            F.col("errors")
        ),
    )
    # Rows are ranked newest first so that superseded observations never take rn=1.
    window = Window.partitionBy(*keys).orderBy(F.col("source_process_date").desc(), F.col("row_id").asc())
    ranked = ranked.withColumn("_rn", F.row_number().over(window))
    return ranked.withColumn(
        "disposition",
        F.when(F.size("errors") > 0, "REJECTED")
        .when(~latest_day, "SUPERSEDED")
        .when(F.col("_rn") > 1, "DUPLICATE")
        .otherwise("CURRENT"),
    ).drop("_latest_date", "_variants", "_rn")
