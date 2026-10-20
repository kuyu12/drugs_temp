"""Complete, read-only extraction into pandas without filesystem storage."""
from datetime import datetime, timezone
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import logging
from threading import Lock, local

import pandas as pd

from .client import RegistryError, RequestLimiter, parse_page
from .record_normalization import digest, json_text, normalize

LOG = logging.getLogger(__name__)


def _fetch_details(client, numbers, workers, requests_per_second):
    def fetch(worker_client, number):
        response = worker_client.details(number)
        return (response["returnObject"]["medicalAccessoriesList"],
                json_text(response), datetime.now(timezone.utc).isoformat())

    results = {}
    if workers == 1:
        for number in numbers:
            results[number] = fetch(client, number)
            if len(results) == 1 or len(results) % 100 == 0:
                LOG.info("Details fetched for %s/%s registrations", len(results), len(numbers))
        return results

    limiter = RequestLimiter(requests_per_second)
    thread_state, clients, clients_lock = local(), [], Lock()

    def load(number):
        if not hasattr(thread_state, "client"):
            worker_client = client.fork(limiter)
            with clients_lock:
                clients.append(worker_client)
            thread_state.client = worker_client
        return fetch(thread_state.client, number)

    # Keep at most workers futures in flight, not one future per registry record.
    iterator = iter(numbers)
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="moh-details")
    pending = {}
    try:
        for number in iterator:
            pending[pool.submit(load, number)] = number
            if len(pending) == workers:
                break
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                results[pending.pop(future)] = future.result()
            if len(results) == 1 or len(results) % 100 == 0:
                LOG.info("Details fetched for %s/%s registrations", len(results), len(numbers))
            for _ in range(len(done)):
                number = next(iterator, None)
                if number is not None:
                    pending[pool.submit(load, number)] = number
    except BaseException:
        limiter.stop()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        for worker_client in clients:
            worker_client.close()
    return results


def fetch_medical_devices_dataframe(client, *, page_size=1000, include_details=True,
                    search="", declaration_only=False, detail_workers=1,
                    requests_per_second=2) -> pd.DataFrame:
    """Retain every listing row and all detail rows for its registration.

    Fail closed on incomplete pages, enrichment errors or observed source changes.
    No files, Spark sessions, Volumes or tables are used. All state is in memory.
    """
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page_size must be 1..1000")
    if type(include_details) is not bool:
        raise ValueError("include_details must be boolean")
    if type(detail_workers) is not int or not 1 <= detail_workers <= 8:
        raise ValueError("detail_workers must be 1..8")
    RequestLimiter(requests_per_second)  # Validate settings before any API work.
    started = datetime.now(timezone.utc).isoformat()
    head = client.search(0, page_size, search, declaration_only)
    first_rows, expected = parse_page(head["returnObject"], 0)
    records, seen_pages = [], set()
    page_count = max(1, (expected + page_size - 1) // page_size)
    for page in range(page_count):
        response = head if page == 0 else client.search(page, page_size, search, declaration_only)
        rows, count = parse_page(response["returnObject"], page)
        if count != expected:
            raise RegistryError("Source total changed; restart extraction")
        if len(rows) != min(page_size, max(0, expected - page * page_size)):
            raise RegistryError("Unexpected page length; possible missing records")
        fingerprint = digest(rows)
        if rows and fingerprint in seen_pages:
            raise RegistryError("Repeated page contents; pagination may be ignored")
        seen_pages.add(fingerprint)
        fetched_at = datetime.now(timezone.utc).isoformat()
        for ordinal, row in enumerate(rows):
            records.append({**row, **normalize(row, started, page, ordinal, fetched_at)})
        LOG.info("Listing page=%s received=%s/%s", page, len(records), expected)

    numbers = list(dict.fromkeys(record["registration_number"] for record in records))
    details_by_registration = (
        _fetch_details(client, numbers, detail_workers, requests_per_second)
        if include_details and numbers else {}
    )
    for record in records:
        number = record["registration_number"]
        rows, raw, fetched_at = details_by_registration.get(number, (None, None, None))
        record.update(details=rows, details_raw_json=raw, details_fetched_at_utc=fetched_at)

    tail = client.search(0, page_size, search, declaration_only)
    tail_rows, final_count = parse_page(tail["returnObject"], 0)
    if final_count != expected or digest(tail_rows) != digest(first_rows):
        raise RegistryError("Source total or head changed during extraction")
    if len(records) != expected:
        raise RegistryError("Extraction is incomplete")
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        columns = list(normalize({"registrationNumber": ""}, started, 0, 0, started))
        frame = pd.DataFrame(columns=columns + ["details", "details_raw_json", "details_fetched_at_utc"])
    frame["expiration_date"] = pd.to_datetime(frame["expiration_date"], format="%Y-%m-%d", errors="coerce")
    frame.attrs["extraction"] = {
        "status": "complete", "source": client.config.base_url,
        "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(frame), "reported_total": expected, "pages": page_count,
        "include_details": include_details, "detail_requests": len(details_by_registration),
        "detail_workers": detail_workers, "requests_per_second": requests_per_second,
        "unique_registration_numbers": frame["registration_number"].nunique(),
    }
    return frame
