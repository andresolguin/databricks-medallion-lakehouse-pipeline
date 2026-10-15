"""Immutable staged inputs, content-addressed Bronze and verified archival."""

import csv
import hashlib
import re
import shutil
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql import types as T

from .contracts import RAW_ALIASES, RAW_FIELDS, REQUIRED_HEADERS, fingerprint
from .storage import QualityError


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover(config):
    if not config.input_dir.exists():
        return []
    items = sorted(config.input_dir.iterdir())
    pattern = re.compile(rf"^iowa_dataset_{config.process_date}(?:_part-?\d+)?\.csv$", re.I)
    files, bad = [], []
    for path in items:
        if path.name.startswith((".", "_")):
            continue
        if path.is_file() and pattern.fullmatch(path.name):
            files.append(path)
        else:
            bad.append(path.name)
    if bad:
        raise ValueError(f"Unexpected input files/directories for {config.process_date}: {bad}")
    has_whole = any(re.fullmatch(rf"iowa_dataset_{config.process_date}\.csv", p.name, re.I) for p in files)
    if has_whole and len(files) > 1:
        raise ValueError("Supply either one complete file or its parts, never both")
    return files


def _read_csv(spark, staged_path):
    with staged_path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), None)
    if not header:
        raise ValueError(f"Empty CSV: {staged_path.name}")
    lowered = [name.strip().lower() for name in header]
    if len(set(lowered)) != len(lowered) or any(not c or "`" in c for c in header):
        raise ValueError("CSV headers must be nonempty, unique and contain no backticks")
    selections, missing = [], []
    for canonical, aliases in RAW_ALIASES.items():
        matches = [header[i] for i, name in enumerate(lowered) if name in {a.lower() for a in aliases}]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous headers for {canonical}: {matches}")
        if not matches and canonical in REQUIRED_HEADERS:
            missing.append(canonical)
        selections.append(
            (F.col(f"`{matches[0]}`") if matches else F.lit(None).cast("string")).alias(canonical)
        )
    if missing:
        raise ValueError(f"Missing required CSV headers: {sorted(missing)}")
    schema = T.StructType([T.StructField(name, T.StringType()) for name in header])
    # Every code path uses this reader. Malformed CSV structure aborts the file;
    # well-formed rows with invalid field values are classified in Silver.
    return (
        spark.read.format("csv")
        .schema(schema)
        .option("header", True)
        .option("multiLine", True)
        .option("quote", '"')
        .option("escape", '"')
        .option("mode", "FAILFAST")
        .option("encoding", "UTF-8")
        .load(str(staged_path))
        .select(*selections)
    )


def ingest(store, run_id):
    config, spark = store.config, store.spark
    store.setup()
    files = discover(config)
    manifest_exists = store.exists("bronze", "file_manifest")
    if not files:
        if manifest_exists:
            known = store.read("bronze", "file_manifest").where(
                (F.col("country") == config.country) & (F.col("process_date") == F.lit(config.delivery_date))
            )
            if known.limit(1).count():
                return {"files_seen": 0, "files_ingested": 0, "already_ingested": True}
        raise FileNotFoundError(f"No delivered CSV files in {config.input_dir}")

    ingested = 0
    for source in files:
        digest = sha256_file(source)
        # Content replay within a delivery is a no-op; the same bytes on a later
        # delivery are a new observation (including an intentional value reversal).
        file_id = hashlib.sha256(f"{config.country}:{config.process_date}:{digest}".encode()).hexdigest()
        receipt_id = hashlib.sha256(f"{source.resolve()}:{file_id}".encode()).hexdigest()
        if store.exists("bronze", "file_manifest"):
            if (
                store.read("bronze", "file_manifest")
                .where(F.col("receipt_id") == receipt_id)
                .limit(1)
                .count()
            ):
                continue
        staged = config.volume_root / "Staging" / config.country / f"{digest}-{source.name}"
        staged.parent.mkdir(parents=True, exist_ok=True)
        if not staged.exists() or sha256_file(staged) != digest:
            shutil.copyfile(source, staged)
        if sha256_file(staged) != digest or sha256_file(source) != digest:
            raise QualityError(
                f"Input changed during staging: {source.name}; producer must deliver immutable files"
            )

        parsed = _read_csv(spark, staged)
        # Count identical physical records instead of losing their multiplicity.
        grouped = parsed.groupBy(*RAW_FIELDS).agg(F.count(F.lit(1)).alias("occurrences"))
        raw = (
            grouped.withColumn("country", F.lit(config.country))
            .withColumn("source_file_id", F.lit(file_id))
            .withColumn("source_sha256", F.lit(digest))
            .withColumn("source_path", F.lit(str(source.resolve())))
            .withColumn("source_file_name", F.lit(source.name))
            .withColumn("source_process_date", F.lit(config.delivery_date))
            .withColumn("ingestion_ts", F.current_timestamp())
            .withColumn("ingestion_run_id", F.lit(run_id))
            .withColumn("_raw_hash", fingerprint(RAW_FIELDS))
            .withColumn("row_id", F.sha2(F.concat_ws(":", "source_file_id", "_raw_hash"), 256))
            .drop("_raw_hash")
        )
        rows = raw.agg(F.sum("occurrences").alias("rows")).first()["rows"]
        if not rows:
            raise QualityError(f"CSV contains no data records: {source.name}")
        # A crash between these commits is recoverable: row_id makes the replay insert-only and idempotent.
        store.merge("bronze", "iowa_raw_str", raw, ["row_id"], partitions=("country", "source_process_date"))
        receipt = spark.range(1).select(
            F.lit(receipt_id).alias("receipt_id"),
            F.lit(file_id).alias("source_file_id"),
            F.lit(digest).alias("sha256"),
            F.lit(config.country).alias("country"),
            F.lit(config.delivery_date).alias("process_date"),
            F.lit(source.name).alias("file_name"),
            F.lit(str(source.resolve())).alias("source_path"),
            F.lit(str(staged)).alias("staged_path"),
            F.lit(str(config.archive_dir / f"{digest}-{source.name}")).alias("archive_path"),
            F.lit(source.stat().st_size).cast("long").alias("size_bytes"),
            F.lit(rows).cast("long").alias("row_count"),
            F.lit(run_id).alias("ingestion_run_id"),
            F.current_timestamp().alias("ingested_at"),
            F.lit(None).cast("timestamp").alias("archived_at"),
            F.lit("INGESTED").alias("status"),
        )
        store.merge("bronze", "file_manifest", receipt, ["receipt_id"])
        ingested += 1
    return {"files_seen": len(files), "files_ingested": ingested, "already_ingested": ingested == 0}


def archive(store):
    """Caller must verify publication first. A successful exit means every receipt is durable."""
    config = store.config
    if not store.exists("bronze", "file_manifest"):
        raise QualityError("No file manifest; ingest and publish before archiving")
    receipts = store.read("bronze", "file_manifest").where(
        (F.col("country") == config.country) & (F.col("process_date") == F.lit(config.delivery_date))
    )
    count = 0
    # File metadata only; no collection of row/business keys to the driver.
    for receipt in receipts.toLocalIterator():
        original, staged, destination = map(
            Path, (receipt.source_path, receipt.staged_path, receipt.archive_path)
        )
        expected = receipt.sha256
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or sha256_file(destination) != expected:
            if not staged.exists() or sha256_file(staged) != expected:
                raise QualityError(f"Missing or changed staged file: {receipt.file_name}")
            shutil.copyfile(staged, destination)
        if sha256_file(destination) != expected:
            raise QualityError(f"Archive verification failed: {receipt.file_name}")
        # A newly delivered revision at the same source path must never be deleted by an older receipt.
        if original.exists() and sha256_file(original) == expected:
            original.unlink()
        if staged.exists():
            staged.unlink()
        if receipt.status != "ARCHIVED":
            store.delta("bronze", "file_manifest").update(
                condition=F.col("receipt_id") == receipt.receipt_id,
                set={"status": F.lit("ARCHIVED"), "archived_at": F.current_timestamp()},
            )
        count += 1
    if count == 0:
        raise QualityError("No ingestion receipts for the requested date")
    return {"verified_archives": count}
