from dataclasses import dataclass


@dataclass(slots=True)
class PipelineInputRow:
    input_drug_name: str
    hebrew_name: str = ""
    english_name: str = ""
    registration_number: str = ""


@dataclass(slots=True)
class PipelineRowResult:
    input_drug_name: str
    autocomplete_candidates: str = ""
    matched_name: str = ""
    registration_number: str = ""
    in_health_basket: str = ""
    basket_inclusion_date: str = ""
    owner: str = ""
    dosage_form: str = ""
    active_components: str = ""
    indications: str = ""
    limitations: str = ""
    use_in_clalit: str = ""
    match_count: int = 0
    match_strategy: str = ""
    query_used: str = ""
    lookup_stage: str = ""
    resolution_status: str = ""
    error: str = ""
