from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re

from .client import RegistryError, parse_page, search_payload

LOG = logging.getLogger(__name__)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(value), encoding="utf-8")


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def file_digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


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


def run_snapshot(client, root: str, run_id: str, *, page_size=1000, search="",
                 declaration_only=False, max_pages: int | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run_id must use only letters, digits, hyphens and underscores")
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise ValueError("max_pages must be positive or None for full extraction")
    base = Path(root) / run_id
    initial_payload = search_payload(0, page_size, search, declaration_only)
    identity = {"api_base": client.config.base_url, "payload": initial_payload, "version": 1}
    identity_path = base / "config.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("Snapshot parameters changed; use a new run_id")
    write_json(identity_path, identity)
    manifest = {"run_id": run_id, "status": "running", "source": client.config.base_url,
                "started_at_utc": datetime.now(timezone.utc).isoformat(), "rows": 0, "pages": 0}
    write_json(base / "manifest.json", manifest)
    try:
        # Always recheck the head against the live source before resuming.
        head = client.search(0, page_size, search, declaration_only)
        first_rows, expected = parse_page(head["returnObject"], 0)
        manifest["reported_total"] = expected
        records, seen_pages, registrations = [], set(), set()
        page = 0
        while True:
            checkpoint = base / "raw" / f"page_{page:06d}.json"
            request = search_payload(page, page_size, search, declaration_only)
            saved = None
            if checkpoint.exists():
                try:
                    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    LOG.warning("Refetching unreadable page %s", page)
            if saved is not None:
                if saved.get("request") != request:
                    raise RegistryError("Checkpoint request mismatch")
                envelope = saved["response"]
                if envelope.get("statusCode") != 200:
                    raise RegistryError("Checkpoint contains an API failure")
                rows, count = parse_page(envelope["returnObject"], page)
                if page == 0 and digest(rows) != digest(first_rows):
                    raise RegistryError("Source head changed; start a new snapshot")
                fetched_at = saved["fetched_at_utc"]
            else:
                envelope = head if page == 0 else client.search(page, page_size, search, declaration_only)
                rows, count = parse_page(envelope["returnObject"], page)
                fetched_at = datetime.now(timezone.utc).isoformat()
                write_json(checkpoint, {"request": request, "response": envelope, "fetched_at_utc": fetched_at})
            if count != expected:
                raise RegistryError("Source total changed; start a new snapshot")
            if len(rows) != min(page_size, max(0, expected - page * page_size)):
                raise RegistryError("Unexpected page length; possible server cap or missing records")
            fingerprint = digest(rows)
            if rows and fingerprint in seen_pages:
                raise RegistryError("Repeated page contents; pagination may be ignored")
            seen_pages.add(fingerprint)
            for ordinal, row in enumerate(rows):
                registrations.add(str(row["registrationNumber"]))
                records.append(normalize(row, run_id, page, ordinal, fetched_at))
            manifest.update(rows=len(records), pages=page + 1)
            write_json(base / "manifest.json", manifest)
            LOG.info("page=%s received=%s/%s", page, len(records), expected)
            if len(records) == expected or (max_pages is not None and page + 1 >= max_pages):
                break
            page += 1
        tail = client.search(0, page_size, search, declaration_only)
        tail_rows, final_count = parse_page(tail["returnObject"], 0)
        if final_count != expected or digest(tail_rows) != digest(first_rows):
            raise RegistryError("Source total or head changed during extraction")
        output = base / "records.jsonl"
        # One sequential write; no append/random writes or rename assumptions on Volumes.
        with output.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json_text(record) + "\n")
        manifest.update(
            status="complete" if len(records) == expected else "sampled",
            unique_registration_numbers=len(registrations),
            duplicate_row_hashes=len(records) - len({record["row_hash"] for record in records}),
            invalid_expiration_dates=sum(bool(r["expiration_date_raw"]) and r["expiration_date"] is None for r in records),
            records_file="records.jsonl", records_sha256=file_digest(output),
        )
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        raise
    finally:
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(base / "manifest.json", manifest)
    return manifest
