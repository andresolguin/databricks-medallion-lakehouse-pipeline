"""The same Delta operations address local paths or Unity Catalog names."""

from delta.tables import DeltaTable


class QualityError(RuntimeError):
    """A failed invariant must stop the job before publication/archival."""


class DeltaStore:
    def __init__(self, spark, config):
        self.spark, self.config = spark, config

    def name(self, layer, table):
        return f"`{self.config.catalog}`.`{self.config.schema(layer)}`.`{table}`"

    def path(self, layer, table):
        from pathlib import Path

        return str(Path(self.config.local_root).resolve() / "tables" / layer / table)

    def setup(self):
        if not self.config.local_root:
            # The caller supplies an existing catalog and CREATE SCHEMA / VOLUME privileges.
            for layer in ("bronze", "silver", "gold"):
                self.spark.sql(
                    f"CREATE SCHEMA IF NOT EXISTS `{self.config.catalog}`.`{self.config.schema(layer)}`"
                )
            self.spark.sql(
                f"CREATE VOLUME IF NOT EXISTS `{self.config.catalog}`."
                f"`{self.config.bronze_schema}`.`{self.config.volume}`"
            )

    def exists(self, layer, table):
        if self.config.local_root:
            return DeltaTable.isDeltaTable(self.spark, self.path(layer, table))
        return self.spark.catalog.tableExists(self.name(layer, table))

    def read(self, layer, table):
        if self.config.local_root:
            return self.spark.read.format("delta").load(self.path(layer, table))
        return self.spark.table(self.name(layer, table))

    def delta(self, layer, table):
        if self.config.local_root:
            return DeltaTable.forPath(self.spark, self.path(layer, table))
        return DeltaTable.forName(self.spark, self.name(layer, table))

    def write(self, layer, table, frame, *, mode="errorifexists", partitions=()):
        writer = frame.write.format("delta").mode(mode)
        if partitions:
            writer = writer.partitionBy(*partitions)
        if self.config.local_root:
            writer.save(self.path(layer, table))
        else:
            writer.saveAsTable(self.name(layer, table))

    def merge(self, layer, table, source, keys, *, update=None, reconcile=False, partitions=()):
        """Source must contain exactly one row per key. Never overwrite an existing fact schema."""
        if not self.exists(layer, table):
            self.write(layer, table, source, partitions=partitions)
            return
        condition = " AND ".join(f"t.`{key}` = s.`{key}`" for key in keys)
        merge = self.delta(layer, table).alias("t").merge(source.alias("s"), condition)
        if update:
            merge = merge.whenMatchedUpdateAll(condition=update)
        merge = merge.whenNotMatchedInsertAll()
        if reconcile:
            # Only safe with the full, validated current snapshot, never an incremental input batch.
            merge = merge.whenNotMatchedBySourceDelete()
        merge.execute()


def require_unique(frame, keys, label):
    from functools import reduce

    from pyspark.sql import functions as F

    null_key = reduce(lambda a, b: a | b, (F.col(k).isNull() for k in keys))
    if frame.where(null_key).limit(1).count():
        raise QualityError(f"{label}: null key in {keys}")
    if frame.groupBy(*keys).count().where("count > 1").limit(1).count():
        raise QualityError(f"{label}: duplicate key in {keys}")
