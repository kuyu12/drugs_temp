from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from math import isfinite
from threading import Event, Lock
from typing import Any
from urllib.parse import urlsplit

import requests


class RegistryError(RuntimeError):
    """API access, contract or transport failure; never an empty result."""


def _raise_response_error(message, response, url, cause=None):
    error = RegistryError(message)
    error.response = response
    error.add_note(f"Request: POST {url}")
    error.add_note(f"HTTP {response.status_code}; Content-Type: {response.headers.get('Content-Type', '')}")
    error.add_note("Full response body (untruncated):\n" + response.text)
    if cause is None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            cause = exc
    if cause is not None:
        raise error from cause
    raise error


class RequestLimiter:
    """Shared request spacing, server cooldown and cancellation for one run."""

    def __init__(self, requests_per_second):
        if isinstance(requests_per_second, bool) or not isinstance(requests_per_second, (int, float)) or not isfinite(requests_per_second) or not 0 < requests_per_second <= 5:
            raise ValueError("requests_per_second must be > 0 and <= 5")
        self.interval = 1 / requests_per_second
        self._next = 0.0
        self._lock = Lock()
        self._stopped = Event()

    def wait(self):
        while not self._stopped.is_set():
            with self._lock:
                now = time.monotonic()
                remaining = self._next - now
                if remaining <= 0:
                    self._next = now + self.interval
                    return
            self._stopped.wait(remaining)
        raise RegistryError("Concurrent extraction cancelled")

    def defer(self, seconds):
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)

    def stop(self):
        self._stopped.set()


@dataclass(frozen=True)
class Config:
    base_url: str = "https://registries.health.gov.il/api/MedicalDevices"
    timeout_seconds: float = 45
    delay_seconds: float = 2
    attempts: int = 3

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.netloc or url.query or url.fragment:
            raise ValueError("An HTTPS API base URL without query or fragment is required")
        if self.timeout_seconds <= 0 or self.delay_seconds < 0 or self.attempts < 1:
            raise ValueError("Invalid request timing configuration")


def search_payload(page: int = 0, page_size: int = 1000, search: str = "",
                   declaration_only: bool = False) -> dict[str, Any]:
    if type(page) is not int or page < 0 or type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page must be nonnegative; page_size must be 1..1000")
    if type(declaration_only) is not bool:
        raise ValueError("declaration_only must be boolean")
    # These misspellings are part of the public frontend's request contract.
    return {
        "pageNumber": page, "accessoryName": "", "registeredOwner": "",
        "manufacter": "", "search": search, "maxResaults": page_size,
        "isDecending": True, "registrationNumber": 0, "accessoryCode": 0,
        "manufacterCode": 0, "registeredOwnerCode": 0,
        "typePremission": declaration_only, "sort": 1,
    }


def parse_page(data: dict[str, Any], requested_page: int) -> tuple[list[dict], int]:
    if not isinstance(data, dict):
        raise RegistryError("Search returnObject is not an object")
    rows, count = data.get("medicalAccessoriesList"), data.get("totalRows")
    if not isinstance(rows, list) or type(count) is not int or count < 0:
        raise RegistryError("Invalid search contract: medicalAccessoriesList/totalRows")
    if data.get("pageNumber") != requested_page:
        raise RegistryError("Response pageNumber does not match request")
    if any(not isinstance(row, dict) or not str(row.get("registrationNumber") or "").strip() for row in rows):
        raise RegistryError("Search record missing registrationNumber")
    return rows, count


class Client:
    def __init__(self, config: Config = Config(), session=None, limiter=None):
        self.config = config
        self.limiter = limiter
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json",
                                     "User-Agent": "moh-medical-devices-pipeline/0.1"})

    def close(self):
        self.session.close()

    def fork(self, limiter):
        # Public API workers use independent sessions; never share Session across threads.
        return Client(replace(self.config, delay_seconds=0), limiter=limiter)

    def post(self, action: str, payload: dict) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/" + action
        for attempt in range(self.config.attempts):
            time.sleep(self.config.delay_seconds)
            if self.limiter is not None:
                self.limiter.wait()
            try:
                response = self.session.post(url,
                                             json=payload, timeout=self.config.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 == self.config.attempts:
                    error = RegistryError(f"Transport failure: {action}")
                    error.add_note(f"Request: POST {url}; attempt {attempt + 1}/{self.config.attempts}")
                    raise error from exc
                time.sleep(2 ** attempt)
                continue
            except requests.RequestException as exc:
                error = RegistryError(f"Request failure: {action}")
                error.add_note(f"Request: POST {url}; attempt {attempt + 1}/{self.config.attempts}")
                raise error from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 == self.config.attempts:
                    _raise_response_error(f"Retry budget exhausted: HTTP {response.status_code} {action}", response, url)
                retry = response.headers.get("Retry-After", "")
                try:
                    wait = float(retry)
                except ValueError:
                    try:
                        wait = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        wait = 2 ** (attempt + 1)
                if self.limiter is not None:
                    self.limiter.defer(max(0, wait))
                else:
                    time.sleep(max(0, wait))
                continue
            if response.status_code != 200:
                _raise_response_error(f"HTTP {response.status_code}: {action}", response, url)
            if "json" not in response.headers.get("Content-Type", "").lower():
                _raise_response_error(f"Non-JSON response, including possible HTML denial: {action}", response, url)
            try:
                envelope = response.json()
            except ValueError as exc:
                _raise_response_error(f"Invalid JSON: {action}", response, url, cause=exc)
            if not isinstance(envelope, dict) or envelope.get("statusCode") != 200:
                _raise_response_error(f"Application failure: {action}", response, url)
            if not isinstance(envelope.get("returnObject"), (dict, list)):
                _raise_response_error(f"Missing returnObject: {action}", response, url)
            return envelope
        raise RegistryError("Retry budget exhausted")

    def search(self, page=0, page_size=1000, search="", declaration_only=False):
        payload = search_payload(page, page_size, search, declaration_only)
        response = self.post("GetMedicalDevicesDataWithParam", payload)
        parse_page(response["returnObject"], page)
        return response

    def details(self, registration_number: str) -> dict[str, Any]:
        if not isinstance(registration_number, str) or not registration_number.isascii() or not registration_number.isdecimal():
            raise ValueError("registration_number must contain ASCII digits only")
        payload = search_payload(0, 20)
        # Numeric JSON is required here. A string produced an HTML 200 denial.
        payload["registrationNumber"] = int(registration_number)
        envelope = self.post("GetMedicalDeviceByRegistrationNumber", payload)
        data = envelope["returnObject"]
        rows = data.get("medicalAccessoriesList") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows or any(
            not isinstance(row, dict) or str(row.get("registrationNumber")) != registration_number for row in rows
        ):
            raise RegistryError("Details missing or registration identity mismatch")
        # Details report totalRows=0 even when a matching record is present.
        return envelope

    def filter_options(self, kind: str, text: str) -> dict[str, Any]:
        actions = {
            "accessory": ("GetAccessoryNameFilter", "accessoryName"),
            "manufacturer": ("GetManufacturesFilter", "manufacter"),
            "owner": ("GetRegisteredOwnerFilter", "registeredOwner"),
        }
        if kind not in actions:
            raise ValueError("kind must be accessory, manufacturer or owner")
        action, field = actions[kind]
        payload = search_payload(0, 20)
        payload[field] = text
        result = self.post(action, payload)
        rows = result["returnObject"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or "name" not in row or "key" not in row for row in rows):
            raise RegistryError("Invalid filter options")
        return result
