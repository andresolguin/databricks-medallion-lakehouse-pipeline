"""Descriptive analytics over published Gold; windows use calendar dates."""

from pyspark.sql import functions as F


def recent_months(facts, months):
    if not isinstance(months, int) or months <= 0:
        raise ValueError("months must be a positive integer")
    dated = facts.withColumn("month_start", F.trunc("sale_date", "month"))
    bound = dated.agg(F.max("month_start").alias("_max_month"))
    return (
        dated.crossJoin(bound)
        .where(
            F.col("month_start").between(
                F.add_months(F.col("_max_month"), -(months - 1)), F.col("_max_month")
            )
        )
        .drop("_max_month")
    )


def monthly_sales(facts, months=24):
    all_months = facts.groupBy(F.trunc("sale_date", "month").alias("month_start")).agg(
        F.sum("sale_dollars").alias("sales_usd"), F.sum("sale_bottles").alias("bottles")
    )
    # Exact calendar join. Missing comparator months remain NULL, never a different month.
    current, previous = all_months.alias("c"), all_months.alias("p")
    joined = current.join(
        previous, F.col("p.month_start") == F.add_months(F.col("c.month_start"), -12), "left"
    )
    joined = joined.select("c.*", F.col("p.sales_usd").alias("sales_prev_year"))
    joined = joined.withColumn(
        "yoy_pct",
        (F.col("sales_usd") - F.col("sales_prev_year"))
        / F.when(F.col("sales_prev_year") != 0, F.col("sales_prev_year"))
        * 100,
    )
    upper = all_months.agg(F.max("month_start").alias("_max_month"))
    return (
        joined.crossJoin(upper)
        .where(F.col("month_start") >= F.add_months(F.col("_max_month"), -(months - 1)))
        .drop("_max_month")
        .orderBy("month_start")
    )


def annual_sales(facts, *, complete_through_year):
    """Completeness is an explicit source watermark, not inferred from today's clock."""
    if not isinstance(complete_through_year, int) or not 1900 <= complete_through_year <= 9999:
        raise ValueError("Provide a confirmed complete_through_year between 1900 and 9999")
    yearly = (
        facts.where(F.year("sale_date") <= complete_through_year)
        .groupBy(F.year("sale_date").alias("year"))
        .agg(F.sum("sale_dollars").alias("sales_usd"))
    )
    c, p = yearly.alias("c"), yearly.alias("p")
    return (
        c.join(p, F.col("p.year") == F.col("c.year") - 1, "left")
        .select("c.*", F.col("p.sales_usd").alias("sales_prev_year"))
        .withColumn(
            "yoy_pct",
            (F.col("sales_usd") - F.col("sales_prev_year"))
            / F.when(F.col("sales_prev_year") != 0, F.col("sales_prev_year"))
            * 100,
        )
        .orderBy("year")
    )


def store_ranking(facts, stores, months=3):
    totals = (
        recent_months(facts, months)
        .groupBy("country", "store_id")
        .agg(F.sum("sale_dollars").alias("sales_usd"), F.sum("sale_bottles").alias("bottles"))
    )
    return totals.join(
        stores.select("country", "store_id", "store_name", "city", "county"), ["country", "store_id"]
    ).orderBy(F.desc("sales_usd"), "country", "store_id")


def category_ranking(facts, items, months=12):
    joined = recent_months(facts, months).join(
        items.select("country", "item_no", "category_name"), ["country", "item_no"]
    )
    return (
        joined.groupBy("category_name")
        .agg(F.sum("sale_dollars").alias("sales_usd"), F.sum("sale_bottles").alias("bottles"))
        .orderBy(F.desc("sales_usd"))
    )


def item_margins(facts, items, months=6):
    totals = (
        recent_months(facts, months)
        .groupBy("country", "item_no")
        .agg(
            F.sum("sale_dollars").alias("revenue_usd"),
            F.sum(F.col("sale_bottles") * F.col("state_bottle_cost")).alias("cost_usd"),
        )
    )
    return (
        totals.withColumn("margin_usd", F.col("revenue_usd") - F.col("cost_usd"))
        .withColumn(
            "margin_pct", F.col("margin_usd") / F.when(F.col("revenue_usd") != 0, F.col("revenue_usd")) * 100
        )
        .join(items.select("country", "item_no", "item_desc"), ["country", "item_no"])
        .orderBy(F.desc("margin_usd"), "country", "item_no")
    )


def item_month_panel(facts, months=36):
    # Descriptions are attributes, not grouping keys: exactly one observation per item/month.
    return (
        recent_months(facts, months)
        .groupBy("country", "item_no", "month_start")
        .agg(F.sum("sale_bottles").alias("qty_bottles"), F.sum("sale_dollars").alias("revenue_usd"))
        .where("qty_bottles > 0 AND revenue_usd > 0")
        .withColumn("unit_price_usd", F.col("revenue_usd") / F.col("qty_bottles"))
    )


def price_volume_association(facts, items, months=36):
    """Exploratory log-log association; no causal claim or automatic price recommendation."""
    panel = (
        item_month_panel(facts, months)
        .withColumn("ln_p", F.log("unit_price_usd"))
        .withColumn("ln_q", F.log("qty_bottles"))
    )
    estimates = panel.groupBy("country", "item_no").agg(
        F.countDistinct("month_start").alias("n_months"),
        F.countDistinct("unit_price_usd").alias("n_prices"),
        F.countDistinct("qty_bottles").alias("n_quantities"),
        F.regr_slope("ln_q", "ln_p").alias("log_log_slope"),
        F.regr_r2("ln_q", "ln_p").alias("r2"),
    )
    return (
        estimates.where("n_months >= 6 AND n_prices >= 2 AND n_quantities >= 2")
        .join(items.select("country", "item_no", "item_desc"), ["country", "item_no"])
        .orderBy("country", "item_no")
    )
