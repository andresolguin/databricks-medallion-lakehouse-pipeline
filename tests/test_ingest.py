import csv

import pytest
from generate_inputs import FIELDS, sale, write_delivery

from iowa_lakehouse.config import PipelineConfig
from iowa_lakehouse.ingest import _read_csv, discover


def test_whole_file_and_parts_cannot_be_mixed(tmp_path):
    write_delivery(tmp_path, "20251018", [sale()])
    write_delivery(tmp_path, "20251018", [sale()], suffix="_part-1")
    with pytest.raises(ValueError, match="never both"):
        discover(PipelineConfig(process_date="20251018", local_root=str(tmp_path)))


def test_both_documented_part_spellings_share_one_validator(tmp_path):
    write_delivery(tmp_path, "20251018", [sale()], suffix="_part-1")
    write_delivery(tmp_path, "20251018", [sale()], suffix="_part02")
    assert len(discover(PipelineConfig(process_date="20251018", local_root=str(tmp_path)))) == 2


def test_csv_multiline_and_public_headers_use_one_reader(spark, tmp_path):
    from iowa_lakehouse.contracts import RAW_ALIASES

    path = tmp_path / "source.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([RAW_ALIASES[c][-1] for c in FIELDS])
        writer.writerow(sale(address="123 Example Street\nSuite 2").values())
    rows = _read_csv(spark, path).collect()
    assert len(rows) == 1 and rows[0].address == "123 Example Street\nSuite 2"
    assert rows[0].invoice_line_no == "INV-1"


def test_structurally_malformed_csv_fails_the_file(spark, tmp_path):
    path = write_delivery(tmp_path, "20251018", [sale()])
    with path.open("a") as stream:
        stream.write("too,few,fields\n")
    with pytest.raises(Exception, match="MALFORMED|malformed"):
        _read_csv(spark, path).collect()


def test_missing_required_header_fails_before_ingestion(spark, tmp_path):
    path = tmp_path / "missing.csv"
    path.write_text("invoice_line_no,date\nINV-1,2025-01-01\n")
    with pytest.raises(ValueError, match="Missing required"):
        _read_csv(spark, path)
