"""Preserve original API fields and add consistent pandas column names."""
from datetime import datetime
import hashlib
import json


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def normalize(row: dict, run_id: str, page: int, ordinal: int, fetched_at: str) -> dict:
    raw_date = row.get("experationDate")
    try:
        expiry = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat() if raw_date else None
    except (TypeError, ValueError):
        expiry = None
    return {
        "run_id": run_id, "source_page": page, "source_row": ordinal,
        "row_hash": digest(row), "fetched_at_utc": fetched_at,
        "registration_number": str(row["registrationNumber"]),
        "product_name_he": row.get("hProductName"), "product_name_en": row.get("eProductName"),
        "expiration_date_raw": raw_date, "expiration_date": expiry,
        "manufacturer_name": row.get("manufacturerName"), "country_created": row.get("countryCreated"),
        "registered_owner": row.get("registeredOwner"), "operator": row.get("operator"),
        "usage_place": row.get("usagePlace"), "expertise": row.get("experties"),
        "description": row.get("description"), "label": row.get("label"),
        "permission_type": row.get("typePermission"), "raw_json": json_text(row),
    }
