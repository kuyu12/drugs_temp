from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Any

import requests


class DrugRegistryError(RuntimeError):
    pass


@dataclass(slots=True)
class DrugRegistryService:
    base_url: str
    timeout_seconds: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    min_request_delay_seconds: float = 1.5
    max_request_delay_seconds: float = 4.0
    retry_attempts: int = 4
    retry_backoff_seconds: float = 3.0
    block_cooldown_seconds: float = 30.0
    cache_dir: str = ".cache/drug_registry"
    cache_ttl_hours: int = 168
    _cache_path: Path = field(init=False, repr=False)
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache_path = Path(self.cache_dir)
        self._cache_path.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
                "Origin": self.base_url.rstrip("/"),
                "Referer": f"{self.base_url.rstrip('/')}/#!/byDrug",
                "User-Agent": self.user_agent,
            }
        )

    def search_by_name(
        self,
        name: str,
        *,
        prescription: bool = False,
        health_services: bool = False,
        page_index: int = 1,
        order_by: int = 0,
    ) -> list[dict[str, Any]]:
        response = self._post(
            "SearchByName",
            {
                "val": name,
                "prescription": prescription,
                "healthServices": health_services,
                "pageIndex": page_index,
                "orderBy": order_by,
            },
        )
        results = response.get("results", [])
        if not isinstance(results, list):
            raise DrugRegistryError("Unexpected response shape from drug registry search")
        return [self._normalize_search_result(item) for item in results if isinstance(item, dict)]

    def check_basket_for_names(self, names: Sequence[str]) -> list[dict[str, Any]]:
        queries: list[dict[str, Any]] = []
        for raw_name in names:
            name = raw_name.strip()
            if not name:
                continue
            queries.append({"query": name, "matches": self.search_by_name(name)})
        return queries

    def search_box_autocomplete(self, value: str) -> list[str]:
        response = self._post(
            "SearchBoxAutocomplete",
            {
                "val": value,
                "isSearchTradeName": True,
                "isSearchTradeMarkiv": False,
            },
        )
        results = response.get("results", [])
        if not isinstance(results, list):
            raise DrugRegistryError("Unexpected response shape from drug registry autocomplete")
        return [item for item in results if isinstance(item, str) and item.strip()]

    def get_specific_drug(self, registration_number: str) -> dict[str, Any]:
        response = self._post("GetSpecificDrug", {"dragRegNum": registration_number})
        return self._normalize_drug_details(response)

    def _post(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        cache_key = self._build_cache_key(action=action, payload=payload)
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            self._sleep_before_request()
            try:
                response = self._session.post(
                    f"{self.base_url.rstrip('/')}/GovServiceList/IDRServer/{action}",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout_seconds,
                )
                data = self._parse_response(response, action)
                self._write_cache(cache_key, data)
                return data
            except requests.Timeout:
                last_error = DrugRegistryError(f"Drug registry request timed out for {action}")
            except requests.RequestException as exc:
                last_error = DrugRegistryError(f"Drug registry request failed for {action}: {exc}")
            except DrugRegistryError as exc:
                last_error = exc

            if attempt < self.retry_attempts:
                self._sleep_after_failure(str(last_error))

        if last_error is not None:
            raise last_error
        raise DrugRegistryError(f"Drug registry request failed for {action}")

    def _parse_response(self, response: requests.Response, action: str) -> dict[str, Any]:
        code = response.status_code
        if code in {403, 429}:
            raise DrugRegistryError(f"Drug registry rate-limited or blocked request for {action} (HTTP {code})")
        if code >= 500:
            raise DrugRegistryError(f"Drug registry server error for {action} (HTTP {code})")
        if code >= 400:
            raise DrugRegistryError(f"Drug registry request rejected for {action} (HTTP {code})")
        try:
            data = response.json()
        except ValueError as exc:
            raise DrugRegistryError(f"Drug registry returned non-JSON response for {action}") from exc
        if not isinstance(data, dict):
            raise DrugRegistryError(f"Unexpected response type from drug registry for {action}")
        return data

    def _sleep_before_request(self) -> None:
        delay = random.uniform(self.min_request_delay_seconds, self.max_request_delay_seconds)
        time.sleep(delay)

    def _sleep_after_failure(self, error_message: str) -> None:
        if "HTTP 403" in error_message or "HTTP 429" in error_message or "rate-limited" in error_message:
            time.sleep(self.block_cooldown_seconds)
            return
        time.sleep(self.retry_backoff_seconds + random.uniform(0, self.retry_backoff_seconds))

    def _build_cache_key(self, *, action: str, payload: dict[str, Any]) -> str:
        raw_key = json.dumps({"action": action, "payload": payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _cache_file(self, cache_key: str) -> Path:
        return self._cache_path / f"{cache_key}.json"

    def _load_cache(self, cache_key: str) -> dict[str, Any] | None:
        cache_file = self._cache_file(cache_key)
        if not cache_file.exists():
            return None
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        cached_at_raw = payload.get("cached_at")
        data = payload.get("data")
        if not isinstance(cached_at_raw, str) or not isinstance(data, dict):
            return None
        try:
            cached_at = datetime.fromisoformat(cached_at_raw)
        except ValueError:
            return None
        if datetime.now(UTC) - cached_at > timedelta(hours=self.cache_ttl_hours):
            return None
        return data

    def _write_cache(self, cache_key: str, data: dict[str, Any]) -> None:
        cache_file = self._cache_file(cache_key)
        cache_payload = {
            "cached_at": datetime.now(UTC).isoformat(),
            "data": data,
        }
        cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _normalize_search_result(item: dict[str, Any]) -> dict[str, Any]:
        active_components = item.get("activeComponents") or []
        return {
            "registration_number": item.get("dragRegNum"),
            "hebrew_name": item.get("dragHebName"),
            "english_name": item.get("dragEnName"),
            "owner": item.get("dragRegOwner"),
            "dosage_form": item.get("dosageForm"),
            "indications": item.get("indications"),
            "in_health_basket": bool(item.get("health")),
            "active_components": [
                component.get("componentName")
                for component in active_components
                if isinstance(component, dict) and component.get("componentName")
            ],
        }

    @staticmethod
    def _normalize_drug_details(item: dict[str, Any]) -> dict[str, Any]:
        active_materials = item.get("activeMetirals") or []
        return {
            "registration_number": item.get("dragRegNum"),
            "hebrew_name": item.get("dragHebName"),
            "english_name": item.get("dragEnName"),
            "owner": item.get("regOwnerName"),
            "manufacturer": item.get("regManufactureName"),
            "dosage_form": item.get("dosageForm"),
            "indications": item.get("dragIndication"),
            "in_health_basket": bool(item.get("health")),
            "date_of_inclusion": item.get("dateOfInclusion"),
            "limitations": item.get("limitations"),
            "use_in_clalit": item.get("useInClalit"),
            "active_components": [
                " ".join(filter(None, [component.get("ingredientsDesc"), component.get("dosage")])).strip()
                for component in active_materials
                if isinstance(component, dict)
            ],
        }
