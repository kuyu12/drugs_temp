from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any
from urllib.parse import urlsplit

import requests


class RegistryError(RuntimeError):
    """API access, contract or transport failure; never an empty result."""


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
    def __init__(self, config: Config = Config(), session=None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json",
                                     "User-Agent": "moh-medical-devices-pipeline/0.1"})

    def close(self):
        self.session.close()

    def post(self, action: str, payload: dict) -> dict[str, Any]:
        for attempt in range(self.config.attempts):
            time.sleep(self.config.delay_seconds)
            try:
                response = self.session.post(self.config.base_url.rstrip("/") + "/" + action,
                                             json=payload, timeout=self.config.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 == self.config.attempts:
                    raise RegistryError(f"Transport failure: {action}") from exc
                time.sleep(2 ** attempt)
                continue
            except requests.RequestException as exc:
                raise RegistryError(f"Request failure: {action}") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 == self.config.attempts:
                    raise RegistryError(f"Retry budget exhausted: HTTP {response.status_code} {action}")
                retry = response.headers.get("Retry-After", "")
                try:
                    wait = float(retry)
                except ValueError:
                    try:
                        wait = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        wait = 2 ** (attempt + 1)
                time.sleep(max(0, wait))
                continue
            if response.status_code != 200:
                raise RegistryError(f"HTTP {response.status_code}: {action}")
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise RegistryError(f"Non-JSON response, including possible HTML denial: {action}")
            try:
                envelope = response.json()
            except ValueError as exc:
                raise RegistryError(f"Invalid JSON: {action}") from exc
            if not isinstance(envelope, dict) or envelope.get("statusCode") != 200:
                raise RegistryError(f"Application failure: {action}")
            if not isinstance(envelope.get("returnObject"), (dict, list)):
                raise RegistryError(f"Missing returnObject: {action}")
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
