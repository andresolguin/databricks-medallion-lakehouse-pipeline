"""Command-line execution. Exceptions propagate as a nonzero process exit."""

import argparse
import json

from .config import PipelineConfig
from .pipeline import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-date", required=True, help="Delivery date YYYYMMDD")
    parser.add_argument("--local-root", help="Use local Delta tables and files under this directory")
    parser.add_argument("--stage", choices=["all", "bronze", "silver", "gold", "archive"], default="all")
    for key, default in [
        ("catalog", "workspace"),
        ("bronze-schema", "iowa_bronze"),
        ("silver-schema", "iowa_silver"),
        ("gold-schema", "iowa_gold"),
        ("volume", "iowa_files"),
        ("country", "usa"),
    ]:
        parser.add_argument(f"--{key}", default=default)
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    config = PipelineConfig(**args)
    if config.local_root:
        from .runtime import local_spark

        spark = local_spark(config.local_root)
    else:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
    try:
        result = execute(spark, config, stage=stage)
        print(json.dumps(result, indent=2, default=str))
    finally:
        if config.local_root:
            spark.stop()


if __name__ == "__main__":
    main()
