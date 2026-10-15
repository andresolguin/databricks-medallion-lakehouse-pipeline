"""Validated parameters; process dates describe delivery, not the sale date."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PipelineConfig:
    process_date: str
    catalog: str = "workspace"
    bronze_schema: str = "iowa_bronze"
    silver_schema: str = "iowa_silver"
    gold_schema: str = "iowa_gold"
    volume: str = "iowa_files"
    country: str = "usa"
    local_root: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"\d{8}", self.process_date):
            raise ValueError("process_date must be a real calendar date in YYYYMMDD format")
        datetime.strptime(self.process_date, "%Y%m%d")
        for name in ("catalog", "bronze_schema", "silver_schema", "gold_schema", "volume"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", getattr(self, name)):
                raise ValueError(f"Invalid SQL identifier: {name}")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", self.country):
            raise ValueError("country must be a lowercase path-safe code, for example usa")
        if len({self.bronze_schema, self.silver_schema, self.gold_schema}) != 3:
            raise ValueError("Bronze, Silver and Gold must use distinct schemas")
        if self.local_root and any(c in str(Path(self.local_root).resolve()) for c in ("`", "\n")):
            raise ValueError("local_root contains an unsupported character")

    @property
    def delivery_date(self):
        return datetime.strptime(self.process_date, "%Y%m%d").date()

    @property
    def volume_root(self):
        if self.local_root:
            return Path(self.local_root).resolve() / "volume"
        return Path(f"/Volumes/{self.catalog}/{self.bronze_schema}/{self.volume}")

    @property
    def date_path(self):
        d = self.delivery_date
        return Path(self.country) / f"yyyy={d:%Y}" / f"mm={d:%m}" / f"dd={d:%d}"

    @property
    def input_dir(self):
        return self.volume_root / "Process" / self.date_path

    @property
    def archive_dir(self):
        return self.volume_root / "Archive" / self.date_path

    def schema(self, layer):
        if layer not in {"bronze", "silver", "gold"}:
            raise ValueError(f"Unknown layer: {layer}")
        return getattr(self, f"{layer}_schema")
