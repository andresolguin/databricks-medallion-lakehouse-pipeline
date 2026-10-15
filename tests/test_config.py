import pytest

from iowa_lakehouse.config import PipelineConfig


@pytest.mark.parametrize("value", ["20250230", "20251301", "2025101", "2025-10-18", "anything"])
def test_invalid_delivery_dates_fail(value):
    with pytest.raises(ValueError):
        PipelineConfig(process_date=value)


def test_parameters_control_paths_and_schemas(tmp_path):
    config = PipelineConfig(
        process_date="20260402",
        catalog="custom",
        country="argentina",
        local_root=str(tmp_path),
        bronze_schema="raw",
        silver_schema="curated",
        gold_schema="analytics",
    )
    assert str(config.input_dir).endswith("volume/Process/argentina/yyyy=2026/mm=04/dd=02")
    assert config.schema("gold") == "analytics"
    assert config.catalog == "custom"


@pytest.mark.parametrize(
    "values", [{"catalog": "a;DROP TABLE b"}, {"country": "../usa"}, {"gold_schema": "iowa_silver"}]
)
def test_unsafe_or_overlapping_names_fail(values):
    with pytest.raises(ValueError):
        PipelineConfig(process_date="20251018", **values)
