from iowa_lakehouse.contracts import classify
from iowa_lakehouse.pipeline import silver_metrics


def collect(raw_frame, rows):
    return [r.asDict() for r in classify(raw_frame(rows)).collect()]


def test_complete_invoice_keys_do_not_collapse(raw_frame):
    rows = collect(
        raw_frame,
        [
            {"invoice_line_no": "INV-14877300005"},
            {"invoice_line_no": "S15183400047"},
            {"invoice_line_no": "INV-UNRELATED", "pack": "0"},
        ],
    )
    assert {r["invoice_line_no"] for r in rows if r["disposition"] == "CURRENT"} == {
        "INV-14877300005",
        "S15183400047",
    }
    assert len([r for r in rows if r["disposition"] == "REJECTED"]) == 1


def test_missing_keys_amounts_and_fractional_units_are_auditable(raw_frame):
    rows = collect(
        raw_frame,
        [
            {"invoice_line_no": None},
            {"invoice_line_no": "INV-2", "store": None},
            {"invoice_line_no": "INV-3", "itemno": "wrong"},
            {"invoice_line_no": "INV-4", "sale_dollars": None},
            {"invoice_line_no": "INV-5", "sale_bottles": "1.5"},
            {"invoice_line_no": "INV-6", "sale_liters": "-4.5"},
            {"invoice_line_no": "INV-7", "state_bottle_cost": "wrong"},
        ],
    )
    assert len(rows) == 7
    assert all(r["disposition"] == "REJECTED" and r["errors"] for r in rows)
    assert all(r["raw_payload"] and r["row_id"] for r in rows)


def test_optional_county_is_nullable_and_integer_decimal_units_are_valid(raw_frame):
    rows = collect(raw_frame, [{"county_number": None, "sale_bottles": "6.0"}])
    assert rows[0]["disposition"] == "CURRENT"
    assert rows[0]["sale_bottles"] == 6
    assert rows[0]["zipcode"] == "01234"


def test_equivalent_duplicates_count_once_and_conserve_physical_rows(raw_frame):
    decisions = classify(raw_frame([{"occurrences": 2}, {}]))
    metrics = silver_metrics(decisions)
    assert metrics == {
        "raw_rows": 3,
        "current_rows": 1,
        "rejected_rows": 0,
        "superseded_rows": 0,
        "duplicate_rows": 2,
    }


def test_same_delivery_conflicts_are_quarantined(raw_frame):
    rows = collect(raw_frame, [{}, {"state_bottle_retail": "16.00", "sale_dollars": "96.00"}])
    assert all(r["disposition"] == "REJECTED" for r in rows)
    assert all("CONFLICTING_LATEST_RECORDS" in r["errors"] for r in rows)


def test_later_invalid_correction_does_not_resurrect_old_sale(raw_frame):
    rows = collect(raw_frame, [{}, {"source_process_date": "2025-10-19", "sale_dollars": None}])
    assert {r["disposition"] for r in rows} == {"SUPERSEDED", "REJECTED"}
    assert not any(r["disposition"] == "CURRENT" for r in rows)


def test_late_backfill_cannot_override_newer_delivery(raw_frame):
    rows = collect(
        raw_frame,
        [
            {"source_process_date": "2025-10-19", "state_bottle_retail": "16.00", "sale_dollars": "96.00"},
            {"source_process_date": "2025-10-17", "ingestion_ts": "2026-01-01 12:00:00"},
        ],
    )
    current = next(r for r in rows if r["disposition"] == "CURRENT")
    assert str(current["sale_dollars"]) == "96.00"


def test_date_formats_and_currency_are_normalized(raw_frame):
    rows = collect(raw_frame, [{"date": "01/15/2024", "sale_dollars": "$90.00"}])
    assert rows[0]["disposition"] == "CURRENT"
    assert str(rows[0]["sale_date"]) == "2024-01-15"
    assert rows[0]["year"] == 2024 and rows[0]["month"] == 1


def test_extreme_numeric_inputs_are_classified_without_arithmetic_failure(raw_frame):
    rows = collect(
        raw_frame,
        [
            {"bottle_volume_ml": "2147483647", "sale_bottles": "2147483647"},
            {"invoice_line_no": "INV-OVERFLOW", "sale_bottles": "2147483648"},
        ],
    )
    assert all(row["disposition"] == "REJECTED" and row["errors"] for row in rows)
