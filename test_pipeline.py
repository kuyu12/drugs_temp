import csv
from pathlib import Path

from app.pipeline import DrugRegistryPipeline


class FakeDrugRegistryService:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.autocomplete_calls: list[str] = []

    def search_by_name(self, name: str) -> list[dict]:
        self.search_calls.append(name)
        if name == "אקמול":
            return [
                {
                    "registration_number": "020 16 20534 00",
                    "hebrew_name": "אקמול",
                    "english_name": "ACAMOL",
                    "owner": "TEVA ISRAEL LTD",
                    "dosage_form": "טבליה",
                    "indications": "Relief of pain and fever.",
                    "in_health_basket": True,
                    "active_components": ["PARACETAMOL 500 MG"],
                }
            ]
        if name == "AROMASIN":
            return [
                {
                    "registration_number": "4011 00 00000 00",
                    "hebrew_name": "ארומזין",
                    "english_name": "AROMASIN",
                    "owner": "PFIZER",
                    "dosage_form": "TAB",
                    "indications": "Cancer therapy.",
                    "in_health_basket": True,
                    "active_components": ["EXEMESTANE"],
                }
            ]
        return []

    def search_box_autocomplete(self, value: str) -> list[str]:
        self.autocomplete_calls.append(value)
        mapping = {
            "אקמול": ["אקמול", "אקמול טבע"],
            "aromasi": ["AROMASIN", "ARAVA 10 MG"],
            "aromas": ["AROMASIN"],
            "aroma": ["AROMASIN"],
            "avastinx": ["AVASTIN", "AVAMYS"],
            "avastinx": ["AVASTIN", "AVAMYS"],
            "avasti": ["AVASTIN", "AVAMYS"],
            "osten": ["FLOLAN INFUSION OF EPOPROSTENOL 1500 MCG"],
        }
        return mapping.get(value, [])

    def get_specific_drug(self, registration_number: str) -> dict:
        return {
            "registration_number": registration_number,
            "hebrew_name": "אקמול",
            "english_name": "ACAMOL",
            "owner": "TEVA ISRAEL LTD",
            "dosage_form": "טבליה",
            "indications": "Relief of pain and fever.",
            "in_health_basket": True,
            "date_of_inclusion": "01/01/1995",
            "limitations": "Approved",
            "use_in_clalit": "Pain",
            "active_components": ["PARACETAMOL 500 MG"],
        }


def test_pipeline_uses_autocomplete_and_search() -> None:
    pipeline = DrugRegistryPipeline(FakeDrugRegistryService(), max_variants_per_drug=3)
    row = pipeline._process_input_row(
        row=type("Row", (), {"input_drug_name": "אקמול", "hebrew_name": "", "english_name": "", "registration_number": ""})(),
        include_details=False,
    )

    assert row.matched_name == "אקמול"
    assert row.autocomplete_candidates == "אקמול | אקמול טבע"
    assert row.lookup_stage == "autocomplete_suggestion"
    assert row.resolution_status == "registry_match"


def test_pipeline_marks_not_found_when_no_autocomplete_suggestions(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name\nלא קיים\n", encoding="utf-8")

    pipeline = DrugRegistryPipeline(FakeDrugRegistryService())
    results = pipeline.run(input_path=input_path, output_path=output_path, include_details=False)

    assert results[0].resolution_status == "not_found_via_autocomplete"
    assert results[0].error == "not_found"


def test_pipeline_marks_api_no_match_when_autocomplete_exists(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name,english_name\nsomething,AVASTINX\n", encoding="utf-8")

    service = FakeDrugRegistryService()
    pipeline = DrugRegistryPipeline(service)
    results = pipeline.run(input_path=input_path, output_path=output_path, include_details=False)

    assert results[0].resolution_status == "autocomplete_candidates_api_no_match"
    assert results[0].autocomplete_candidates


def test_pipeline_rejects_irrelevant_autocomplete_candidate(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name,english_name\nostenil,OSTENIL\n", encoding="utf-8")

    pipeline = DrugRegistryPipeline(FakeDrugRegistryService())
    results = pipeline.run(input_path=input_path, output_path=output_path, include_details=False)

    assert results[0].resolution_status == "not_found_via_autocomplete"
    assert results[0].autocomplete_candidates == ""


def test_pipeline_writes_partial_output_after_each_row(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name\nאקמול\nלא קיים\n", encoding="utf-8")

    pipeline = DrugRegistryPipeline(FakeDrugRegistryService())
    results = pipeline.run(input_path=input_path, output_path=output_path, include_details=False)

    rows = list(csv.DictReader(output_path.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 2
    assert len(results) == 2


def test_pipeline_limits_variants_per_drug(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name,english_name\nx,AROMASINX\n", encoding="utf-8")

    service = FakeDrugRegistryService()
    pipeline = DrugRegistryPipeline(service, max_variants_per_drug=1)
    pipeline.run(input_path=input_path, output_path=output_path, include_details=False)

    assert len(service.search_calls) <= 1


def test_pipeline_uses_registration_number_when_available(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("drug_name,registration_number\nאקמול,020 16 20534 00\n", encoding="utf-8")

    service = FakeDrugRegistryService()
    pipeline = DrugRegistryPipeline(service)
    results = pipeline.run(input_path=input_path, output_path=output_path)

    assert results[0].match_strategy == "registration_number"
    assert results[0].lookup_stage == "get_specific_drug"
    assert service.search_calls == []


def test_pipeline_cleans_production_style_drug_names() -> None:
    assert DrugRegistryPipeline._clean_input_value("(abraxane (N                                      ") == "abraxane"
    assert DrugRegistryPipeline._clean_input_value("targretin (ייבוא)") == "targretin"
    assert DrugRegistryPipeline._clean_input_value("daivonex  onitment") == "daivonex onitment"
