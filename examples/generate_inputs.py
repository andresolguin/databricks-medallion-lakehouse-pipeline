"""Generate small, entirely synthetic deliveries without downloading third-party data."""

import argparse
import csv
from pathlib import Path

FIELDS = [
    "invoice_line_no",
    "date",
    "store",
    "name",
    "address",
    "city",
    "zipcode",
    "store_location",
    "county_number",
    "county",
    "category",
    "category_name",
    "vendor_no",
    "vendor_name",
    "itemno",
    "im_desc",
    "pack",
    "bottle_volume_ml",
    "state_bottle_cost",
    "state_bottle_retail",
    "sale_bottles",
    "sale_dollars",
    "sale_liters",
    "sale_gallons",
]


def sale(**changes):
    row = dict(
        zip(
            FIELDS,
            [
                "INV-1",
                "2024-01-15",
                "1",
                "Example Store",
                "123 Example Street",
                "Example City",
                "01234",
                "",
                "1",
                "Example County",
                "101",
                "Example Category",
                "10",
                "Example Vendor",
                "100",
                "Example Item",
                "12",
                "750",
                "10.00",
                "15.00",
                "6",
                "90.00",
                "4.500",
                "1.189",
            ],
        )
    )
    return {**row, **changes}


def write_delivery(root, process_date, rows, *, suffix=""):
    directory = (
        Path(root)
        / "volume/Process/usa"
        / f"yyyy={process_date[:4]}"
        / f"mm={process_date[4:6]}"
        / f"dd={process_date[6:8]}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"iowa_dataset_{process_date}{suffix}.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def generate(root):
    first = [
        sale(),
        sale(),
        sale(
            invoice_line_no="INV-2",
            store="2",
            name="Second Example Store",
            address="456 Example Street\nSuite 2",
            date="2024-02-15",
            itemno="200",
        ),
        sale(invoice_line_no="S123456", date="2023-03-01"),
        sale(invoice_line_no="", sale_dollars=""),
        sale(invoice_line_no="INV-BAD", sale_bottles="1.5"),
    ]
    second = [
        sale(state_bottle_retail="16.00", sale_dollars="96.00"),
        sale(invoice_line_no="INV-3", date="2025-05-23"),
    ]
    return [write_delivery(root, "20251018", first), write_delivery(root, "20251019", second)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".state/demo")
    for path in generate(parser.parse_args().root):
        print(path)
