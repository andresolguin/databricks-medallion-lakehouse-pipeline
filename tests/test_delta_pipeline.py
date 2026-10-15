from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from generate_inputs import generate, sale, write_delivery

from iowa_lakehouse.config import PipelineConfig
from iowa_lakehouse.ingest import ingest, sha256_file
from iowa_lakehouse.pipeline import build_silver, execute, publish_gold, verify_gold
from iowa_lakehouse.storage import DeltaStore, QualityError

pytestmark = pytest.mark.integration


def test_fresh_run_replay_correction_backfill_and_recovery(spark, tmp_path, monkeypatch):
    generate(tmp_path)
    first = PipelineConfig(process_date="20251018", local_root=str(tmp_path))
    store = DeltaStore(spark, first)

    # Fresh run: true Delta writes and MERGE, multiline CSV, duplicate and rejected records.
    result = execute(spark, first)
    assert result["silver"] == {
        "raw_rows": 6,
        "current_rows": 3,
        "rejected_rows": 2,
        "superseded_rows": 0,
        "duplicate_rows": 1,
    }
    assert result["gold"]["fact_rows"] == 3
    assert Decimal(result["gold"]["sales_usd"]) == Decimal("270.00")
    assert not list(first.input_dir.glob("*.csv"))
    manifest = store.read("bronze", "file_manifest").first()
    assert manifest.status == "ARCHIVED" and sha256_file(manifest.archive_path) == manifest.sha256
    facts = store.read("gold", "fact_sales")
    assert facts.where("year != year(sale_date) OR month != month(sale_date)").count() == 0
    assert store.read("gold", "dim_store").where("store_id=1").first().zipcode == "01234"
    fact_version = store.delta("gold", "fact_sales").history(1).first().version

    # Replay after sources were archived is a no-op for published Delta data.
    replay = execute(spark, first)
    assert replay["replay"] is True and replay["gold"] == result["gold"]
    assert store.delta("gold", "fact_sales").history(1).first().version == fact_version

    # A later delivery updates INV-1 and adds INV-3 without removing historical years.
    second = replace(first, process_date="20251019")
    corrected = execute(spark, second)
    assert corrected["gold"]["fact_rows"] == 4
    assert Decimal(corrected["gold"]["sales_usd"]) == Decimal("366.00")
    assert (
        str(store.read("gold", "fact_sales").where("invoice_line_no='INV-1'").first().sale_dollars) == "96.00"
    )

    # Late-arriving old delivery cannot undo the newer correction.
    write_delivery(tmp_path, "20251017", [sale(state_bottle_retail="14.00", sale_dollars="84.00")])
    backfill = execute(spark, replace(first, process_date="20251017"))
    assert backfill["gold"]["sales_usd"] == "366.00"

    # Failure before publication: files stay in Process and Archive refuses to run.
    failed_date = replace(first, process_date="20251020")
    pending = write_delivery(tmp_path, "20251020", [sale(invoice_line_no="INV-4", date="2025-05-24")])
    pending_store = DeltaStore(spark, failed_date)
    ingest(pending_store, "interrupted-run")
    with pytest.raises(QualityError, match="Silver does not yet"):
        execute(spark, failed_date, stage="archive")
    assert pending.exists()
    import iowa_lakehouse.ingest as ingest_module

    copyfile = ingest_module.shutil.copyfile

    def interrupted_copy(source, destination, *args, **kwargs):
        if "Archive" in Path(destination).parts:
            Path(destination).write_bytes(b"interrupted archive copy")
            raise OSError("simulated interrupted archive")
        return copyfile(source, destination, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(ingest_module.shutil, "copyfile", interrupted_copy)
        with pytest.raises(OSError, match="simulated interrupted"):
            execute(spark, failed_date)
    assert pending.exists()
    resumed = execute(spark, failed_date)
    assert resumed["gold"]["fact_rows"] == 5 and not pending.exists()

    # An invalid latest correction is quarantined and its previously published fact is removed.
    write_delivery(tmp_path, "20251021", [sale(invoice_line_no="INV-4", sale_dollars="")])
    invalid = execute(spark, replace(first, process_date="20251021"))
    assert invalid["gold"]["fact_rows"] == 4
    assert store.read("gold", "fact_sales").where("invoice_line_no='INV-4'").count() == 0
    assert (
        store.read("silver", "iowa_records")
        .where("invoice_line_no='INV-4' AND disposition='REJECTED'")
        .count()
        == 1
    )

    # The publish gate detects actual measure corruption, not only a stored hash/count.
    store.delta("gold", "fact_sales").update("invoice_line_no='INV-1'", {"sale_dollars": "1.00"})
    with pytest.raises(QualityError, match="do not match"):
        verify_gold(store)
    restored = execute(spark, replace(first, process_date="20251021"))
    assert restored["gold"]["sales_usd"] == "366.00"

    # A genuine later delivery may intentionally revert to byte-identical older contents.
    reverted_path = write_delivery(tmp_path, "20251022", [])
    reverted_path.write_bytes(Path(manifest.archive_path).read_bytes())
    reverted = execute(spark, replace(first, process_date="20251022"))
    assert reverted["gold"]["sales_usd"] == "360.00"
    assert (
        str(store.read("gold", "fact_sales").where("invoice_line_no='INV-1'").first().sale_dollars) == "90.00"
    )


def test_all_rejected_blocks_publication_and_keeps_input(spark, tmp_path):
    config = PipelineConfig(process_date="20260102", local_root=str(tmp_path))
    path = write_delivery(tmp_path, "20260102", [sale(invoice_line_no="", pack="wrong")])
    store = DeltaStore(spark, config)
    ingest(store, "invalid-input")
    with pytest.raises(QualityError, match="No valid current"):
        build_silver(store)
    assert path.exists() and not store.exists("gold", "fact_sales")
    assert store.read("silver", "iowa_records").first().disposition == "REJECTED"


def test_gold_rejects_a_nonunique_source(spark, tmp_path, raw_frame):
    from iowa_lakehouse.contracts import classify

    config = PipelineConfig(process_date="20251018", local_root=str(tmp_path))
    store = DeltaStore(spark, config)
    one = classify(raw_frame([{}])).where("disposition='CURRENT'")
    store.write("silver", "iowa_records", one.unionByName(one))
    with pytest.raises(QualityError, match="duplicate key"):
        publish_gold(store)
    assert not store.exists("gold", "fact_sales")


def test_retry_between_bronze_and_manifest_commits_is_idempotent(spark, tmp_path, monkeypatch):
    config = PipelineConfig(process_date="20260102", local_root=str(tmp_path))
    write_delivery(tmp_path, "20260102", [sale()])
    store = DeltaStore(spark, config)
    original_merge = store.merge

    def interrupted_manifest(layer, table, *args, **kwargs):
        if table == "file_manifest":
            raise RuntimeError("simulated failure before manifest commit")
        return original_merge(layer, table, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(store, "merge", interrupted_manifest)
        with pytest.raises(RuntimeError, match="before manifest"):
            ingest(store, "first-attempt")
    assert store.read("bronze", "iowa_raw_str").count() == 1
    ingest(store, "retry")
    assert store.read("bronze", "iowa_raw_str").count() == 1
    assert store.read("bronze", "file_manifest").count() == 1
