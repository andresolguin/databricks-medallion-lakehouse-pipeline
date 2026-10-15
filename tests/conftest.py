import sys
from pathlib import Path

import pytest
from pyspark.sql import functions as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from generate_inputs import FIELDS, sale  # noqa: E402

from iowa_lakehouse.runtime import local_spark  # noqa: E402


@pytest.fixture(scope="session")
def spark(tmp_path_factory):
    session = local_spark(tmp_path_factory.mktemp("spark"))
    session.conf.set("spark.sql.shuffle.partitions", "1")
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture
def raw_frame(spark):
    def build(observations):
        frames = []
        for index, observation in enumerate(observations):
            row = sale(**{k: v for k, v in observation.items() if k in FIELDS})
            metadata = {
                "country": "usa",
                "row_id": str(index),
                "source_file_id": f"file-{index}",
                "source_sha256": f"sha-{index}",
                "source_path": f"/example/{index}.csv",
                "source_file_name": f"{index}.csv",
                "source_process_date": "2025-10-18",
                "ingestion_ts": "2025-10-18 12:00:00",
                "ingestion_run_id": "test",
                "occurrences": 1,
            }
            metadata.update({k: v for k, v in observation.items() if k not in FIELDS})
            frame = spark.range(1).select(
                *[F.lit(v).cast("string").alias(k) for k, v in row.items()],
                *[F.lit(v).alias(k) for k, v in metadata.items()],
            )
            frame = (
                frame.withColumn("source_process_date", F.col("source_process_date").cast("date"))
                .withColumn("ingestion_ts", F.col("ingestion_ts").cast("timestamp"))
                .withColumn("occurrences", F.col("occurrences").cast("long"))
            )
            frames.append(frame)
        result = frames[0]
        for frame in frames[1:]:
            result = result.unionByName(frame)
        return result

    return build
