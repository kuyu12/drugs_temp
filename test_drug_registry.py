from pathlib import Path
import tempfile
from unittest.mock import patch

from app.services.drug_registry import DrugRegistryService


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_check_basket_for_names_normalizes_matches() -> None:
    response = FakeResponse(
        {
            "results": [
                {
                    "dragRegNum": "020 16 20534 00",
                    "dragHebName": "אקמול",
                    "dragEnName": "ACAMOL",
                    "dragRegOwner": "TEVA ISRAEL LTD",
                    "dosageForm": "טבליה",
                    "indications": "Relief of pain and fever.",
                    "health": True,
                    "activeComponents": [{"componentName": "PARACETAMOL 500 MG"}],
                }
            ]
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("requests.Session.post", return_value=response) as post_mock:
            service = DrugRegistryService(
                base_url="https://israeldrugs.health.gov.il",
                cache_dir=tmp_dir,
                min_request_delay_seconds=0,
                max_request_delay_seconds=0,
            )
            results = service.check_basket_for_names(["אקמול"])

        post_mock.assert_called_once()
        _, kwargs = post_mock.call_args
        assert kwargs["timeout"] == 20.0
        assert kwargs["data"].decode("utf-8") == '{"val": "אקמול", "prescription": false, "healthServices": false, "pageIndex": 1, "orderBy": 0}'
    assert results[0]["matches"][0]["in_health_basket"] is True


def test_get_specific_drug_normalizes_details() -> None:
    response = FakeResponse(
        {
            "dragRegNum": "020 16 20534 00",
            "dragHebName": "אקמול",
            "dragEnName": "ACAMOL",
            "regOwnerName": "TEVA ISRAEL LTD",
            "regManufactureName": "TEVA ISRAEL LTD, ISRAEL",
            "dosageForm": "טבליה",
            "dragIndication": "Relief of pain and fever.",
            "health": True,
            "dateOfInclusion": "01/01/1995",
            "limitations": "Approved for general HMO use",
            "useInClalit": "Mild to moderate pain",
            "activeMetirals": [{"ingredientsDesc": "PARACETAMOL", "dosage": "500 MG"}],
        }
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("requests.Session.post", return_value=response):
            service = DrugRegistryService(
                base_url="https://israeldrugs.health.gov.il",
                cache_dir=tmp_dir,
                min_request_delay_seconds=0,
                max_request_delay_seconds=0,
            )
            result = service.get_specific_drug("020 16 20534 00")

    assert result["hebrew_name"] == "אקמול"
    assert result["in_health_basket"] is True
    assert result["date_of_inclusion"] == "01/01/1995"
    assert result["active_components"] == ["PARACETAMOL 500 MG"]


def test_search_uses_cache_after_first_call() -> None:
    response = FakeResponse(
        {"results": [{"dragRegNum": "020 16 20534 00", "dragHebName": "אקמול", "health": True, "activeComponents": []}]}
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = DrugRegistryService(
            base_url="https://israeldrugs.health.gov.il",
            cache_dir=tmp_dir,
            min_request_delay_seconds=0,
            max_request_delay_seconds=0,
        )
        with patch("requests.Session.post", return_value=response) as post_mock:
            first = service.search_by_name("אקמול")
            second = service.search_by_name("אקמול")

    assert first == second
    post_mock.assert_called_once()
