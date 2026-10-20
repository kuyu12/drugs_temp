"""Prepare a DataFrame and DDL; this module never executes a table write."""
import json
from pathlib import Path
import re

from .pipeline import file_digest

COLUMNS = [
    ("run_id", "STRING"), ("source_page", "INT"), ("source_row", "INT"),
    ("row_hash", "STRING"), ("fetched_at_utc", "STRING"),
    ("registration_number", "STRING"), ("product_name_he", "STRING"), ("product_name_en", "STRING"),
    ("expiration_date_raw", "STRING"), ("expiration_date", "DATE"),
    ("manufacturer_name", "STRING"), ("country_created", "STRING"), ("registered_owner", "STRING"),
    ("operator", "STRING"), ("usage_place", "STRING"), ("expertise", "STRING"),
    ("description", "STRING"), ("label", "STRING"), ("permission_type", "STRING"), ("raw_json", "STRING"),
]


def table_ddl(table_name: str) -> str:
    parts = table_name.split(".")
    if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
        raise ValueError("Use a catalog.schema.table identifier with letters, digits and underscores")
    name = ".".join(f"`{part}`" for part in parts)
    fields = ",\n  ".join(f"`{column}` {kind}" for column, kind in COLUMNS)
    return f"CREATE TABLE IF NOT EXISTS {name} (\n  {fields}\n) USING DELTA PARTITIONED BY (run_id);"


def prepare_dataframe(spark, snapshot_dir: str):
    base = Path(snapshot_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "complete" or manifest["rows"] != manifest["reported_total"]:
        raise ValueError("Only complete snapshots can be prepared for publication")
    records = base / "records.jsonl"
    if file_digest(records) != manifest["records_sha256"]:
        raise ValueError("Snapshot file checksum mismatch")
    schema = ", ".join(f"`{column}` {kind}" for column, kind in COLUMNS)
    frame = spark.read.schema(schema).option("mode", "FAILFAST").option("dateFormat", "yyyy-MM-dd").json(str(records))
    if frame.count() != manifest["rows"]:
        raise ValueError("DataFrame count differs from snapshot manifest")
    return frame
