"""Thin widget bridge. Business logic stays in the tested Python package."""

import json

from .config import PipelineConfig
from .pipeline import execute


def run_stage(spark, dbutils, stage):
    defaults = {
        "catalog": "workspace",
        "bronze_schema": "iowa_bronze",
        "silver_schema": "iowa_silver",
        "gold_schema": "iowa_gold",
        "volume": "iowa_files",
        "country": "usa",
        "process_date": "",
    }
    values = {}
    for name, default in defaults.items():
        try:
            values[name] = dbutils.widgets.get(name)
        except Exception:
            dbutils.widgets.text(name, default)
            values[name] = default
    config = PipelineConfig(**values)
    result = execute(spark, config, stage=stage)
    print(json.dumps(result, indent=2, default=str))
    return result
