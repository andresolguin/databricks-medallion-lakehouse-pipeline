"""Local Spark setup; Databricks supplies its own Spark/Delta session."""

import os
from pathlib import Path

from pyspark.sql import SparkSession


def local_spark(root):
    builder = (
        SparkSession.builder.master(os.environ.get("SPARK_MASTER", "local[2]"))
        .appName("Iowa Lakehouse")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.warehouse.dir", str(Path(root).resolve() / "warehouse"))
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.databricks.delta.snapshotPartitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )
    if os.environ.get("DELTA_JARS"):
        builder = builder.config("spark.jars", os.environ["DELTA_JARS"])
    else:
        from delta import configure_spark_with_delta_pip

        builder = configure_spark_with_delta_pip(builder)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
