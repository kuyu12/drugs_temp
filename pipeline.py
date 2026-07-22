import csv
from dataclasses import asdict
from pathlib import Path
import re
from typing import Any

from app.schemas import PipelineInputRow, PipelineRowResult
from app.services.drug_registry import DrugRegistryError, DrugRegistryService


class DrugRegistryPipeline:
    def __init__(self, service: DrugRegistryService, max_variants_per_drug: int = 3) -> None:
        self.service = service
        self.max_variants_per_drug = max_variants_per_drug

    def run(
        self,
        *,
        input_path: Path,
        output_path: Path,
        input_column: str = "drug_name",
        include_details: bool = True,
        resume: bool = True,
    ) -> list[PipelineRowResult]:
        rows = self._read_input_rows(input_path=input_path, input_column=input_column)
        existing_results = self._load_existing_results(output_path) if resume else {}
        results_by_key: dict[str, PipelineRowResult] = {}
        processed_rows: list[PipelineInputRow] = []

        for row in rows:
            processed_rows.append(row)
            row_key = self._row_key(row)
            if row_key in results_by_key:
                self._write_progress(output_path=output_path, processed_rows=processed_rows, results_by_key=results_by_key)
                continue
            if row_key in existing_results:
                existing = existing_results[row_key]
                if existing.registration_number or existing.resolution_status == "not_found_via_autocomplete":
                    results_by_key[row_key] = existing
                    self._write_progress(output_path=output_path, processed_rows=processed_rows, results_by_key=results_by_key)
                    continue
            results_by_key[row_key] = self._process_input_row(row=row, include_details=include_details)
            self._write_progress(output_path=output_path, processed_rows=processed_rows, results_by_key=results_by_key)

        results = [results_by_key[self._row_key(row)] for row in rows if self._row_key(row) in results_by_key]
        self._write_output_rows(output_path=output_path, results=results)
        return results

    def _read_input_rows(self, *, input_path: Path, input_column: str) -> list[PipelineInputRow]:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or input_column not in reader.fieldnames:
                raise ValueError(f"Input file must contain a '{input_column}' column")

            rows: list[PipelineInputRow] = []
            for row in reader:
                input_name = self._clean_input_value((row.get(input_column, "") or "").strip())
                hebrew_name = self._clean_input_value((row.get("hebrew_name", "") or "").strip())
                english_name = self._clean_input_value((row.get("english_name", "") or "").strip())
                registration_number = (row.get("registration_number", "") or "").strip()
                if not any([input_name, hebrew_name, english_name, registration_number]):
                    continue
                rows.append(
                    PipelineInputRow(
                        input_drug_name=input_name or hebrew_name or english_name or registration_number,
                        hebrew_name=hebrew_name,
                        english_name=english_name,
                        registration_number=registration_number,
                    )
                )
            return rows

    def _process_input_row(self, *, row: PipelineInputRow, include_details: bool) -> PipelineRowResult:
        if row.registration_number:
            return self._resolve_by_registration_number(row=row, include_details=include_details)

        autocomplete_queries = self._build_autocomplete_queries(row)
        autocomplete_candidates: list[str] = []
        last_error = ""

        for query in autocomplete_queries:
            try:
                suggestions = self.service.search_box_autocomplete(query)
            except DrugRegistryError as exc:
                last_error = str(exc)
                continue

            for suggestion in suggestions:
                if not self._is_relevant_autocomplete_candidate(row=row, candidate=suggestion):
                    continue
                if suggestion not in autocomplete_candidates:
                    autocomplete_candidates.append(suggestion)
                if len(autocomplete_candidates) >= self.max_variants_per_drug:
                    break
            if autocomplete_candidates:
                break

        candidates_str = " | ".join(autocomplete_candidates)
        if not autocomplete_candidates:
            if last_error:
                return PipelineRowResult(
                    input_drug_name=row.input_drug_name,
                    query_used=autocomplete_queries[0] if autocomplete_queries else "",
                    lookup_stage="autocomplete",
                    resolution_status="autocomplete_error",
                    error=last_error,
                )
            return PipelineRowResult(
                input_drug_name=row.input_drug_name,
                query_used=autocomplete_queries[0] if autocomplete_queries else "",
                lookup_stage="autocomplete",
                resolution_status="not_found_via_autocomplete",
                match_strategy="not_found_via_autocomplete",
                error="not_found",
            )

        for suggestion in autocomplete_candidates[: self.max_variants_per_drug]:
            try:
                matches = self.service.search_by_name(suggestion)
            except DrugRegistryError as exc:
                last_error = str(exc)
                continue
            if not matches:
                continue
            selected_match, strategy = self._select_best_match(drug_name=suggestion, matches=matches)
            details = self._load_details(selected_match, include_details)
            return PipelineRowResult(
                input_drug_name=row.input_drug_name,
                autocomplete_candidates=candidates_str,
                matched_name=selected_match.get("hebrew_name") or selected_match.get("english_name") or "",
                registration_number=selected_match.get("registration_number") or "",
                in_health_basket=str(bool(selected_match.get("in_health_basket"))).lower(),
                basket_inclusion_date=details.get("date_of_inclusion") or "",
                owner=selected_match.get("owner") or "",
                dosage_form=selected_match.get("dosage_form") or "",
                active_components=", ".join(selected_match.get("active_components") or []),
                indications=selected_match.get("indications") or "",
                limitations=details.get("limitations") or "",
                use_in_clalit=details.get("use_in_clalit") or "",
                match_count=len(matches),
                match_strategy=strategy,
                query_used=suggestion,
                lookup_stage="autocomplete_suggestion",
                resolution_status="registry_match",
                error=details.get("details_error") or "",
            )

        return PipelineRowResult(
            input_drug_name=row.input_drug_name,
            autocomplete_candidates=candidates_str,
            matched_name=autocomplete_candidates[0],
            match_count=0,
            match_strategy="autocomplete_candidates_api_no_match",
            query_used=autocomplete_candidates[0],
            lookup_stage="autocomplete",
            resolution_status="autocomplete_candidates_api_no_match",
            error=last_error or "api_no_match",
        )

    def _resolve_by_registration_number(self, *, row: PipelineInputRow, include_details: bool) -> PipelineRowResult:
        try:
            details = self.service.get_specific_drug(row.registration_number)
        except DrugRegistryError as exc:
            return PipelineRowResult(
                input_drug_name=row.input_drug_name,
                registration_number=row.registration_number,
                query_used=row.registration_number,
                lookup_stage="get_specific_drug",
                resolution_status="registry_error",
                error=str(exc),
            )

        return PipelineRowResult(
            input_drug_name=row.input_drug_name,
            matched_name=details.get("hebrew_name") or details.get("english_name") or "",
            registration_number=details.get("registration_number") or "",
            in_health_basket=str(bool(details.get("in_health_basket"))).lower(),
            basket_inclusion_date=details.get("date_of_inclusion") or "",
            owner=details.get("owner") or "",
            dosage_form=details.get("dosage_form") or "",
            active_components=", ".join(details.get("active_components") or []),
            indications=details.get("indications") or "",
            limitations=details.get("limitations") or "",
            use_in_clalit=details.get("use_in_clalit") or "",
            match_count=1,
            match_strategy="registration_number",
            query_used=row.registration_number,
            lookup_stage="get_specific_drug",
            resolution_status="registry_match",
            error="",
        )

    def _build_autocomplete_queries(self, row: PipelineInputRow) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()
        for value in [row.hebrew_name, row.english_name, row.input_drug_name]:
            normalized = self._normalize_text(value)
            if not normalized:
                continue
            token = normalized.split()[0]
            for candidate in [normalized, token[:8], token[:6], token[:5]]:
                candidate = candidate.strip()
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                queries.append(candidate)
        return queries

    def _load_details(self, selected_match: dict[str, Any], include_details: bool) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if include_details and selected_match.get("registration_number"):
            try:
                details = self.service.get_specific_drug(selected_match["registration_number"])
            except DrugRegistryError as exc:
                details = {"limitations": "", "use_in_clalit": "", "date_of_inclusion": "", "details_error": str(exc)}
        return details

    def _write_progress(
        self,
        *,
        output_path: Path,
        processed_rows: list[PipelineInputRow],
        results_by_key: dict[str, PipelineRowResult],
    ) -> None:
        partial_results = [results_by_key[self._row_key(row)] for row in processed_rows if self._row_key(row) in results_by_key]
        self._write_output_rows(output_path=output_path, results=partial_results)

    def _write_output_rows(self, *, output_path: Path, results: list[PipelineRowResult]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(PipelineRowResult(input_drug_name="")).keys()))
            writer.writeheader()
            for result in results:
                writer.writerow(asdict(result))

    def _load_existing_results(self, output_path: Path) -> dict[str, PipelineRowResult]:
        if not output_path.exists():
            return {}
        with output_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            existing: dict[str, PipelineRowResult] = {}
            for row in reader:
                input_drug_name = (row.get("input_drug_name") or "").strip()
                if not input_drug_name:
                    continue
                input_row = PipelineInputRow(input_drug_name=input_drug_name)
                existing[self._row_key(input_row)] = PipelineRowResult(
                    input_drug_name=input_drug_name,
                    autocomplete_candidates=row.get("autocomplete_candidates", ""),
                    matched_name=row.get("matched_name", ""),
                    registration_number=row.get("registration_number", ""),
                    in_health_basket=row.get("in_health_basket", ""),
                    basket_inclusion_date=row.get("basket_inclusion_date", ""),
                    owner=row.get("owner", ""),
                    dosage_form=row.get("dosage_form", ""),
                    active_components=row.get("active_components", ""),
                    indications=row.get("indications", ""),
                    limitations=row.get("limitations", ""),
                    use_in_clalit=row.get("use_in_clalit", ""),
                    match_count=int(row.get("match_count", "0") or 0),
                    match_strategy=row.get("match_strategy", ""),
                    query_used=row.get("query_used", ""),
                    lookup_stage=row.get("lookup_stage", ""),
                    resolution_status=row.get("resolution_status", ""),
                    error=row.get("error", ""),
                )
            return existing

    def _row_key(self, row: PipelineInputRow) -> str:
        return "|".join(
            [
                row.input_drug_name.strip(),
                row.hebrew_name.strip(),
                row.english_name.strip(),
                row.registration_number.strip(),
            ]
        )

    @staticmethod
    def _select_best_match(*, drug_name: str, matches: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        normalized_query = DrugRegistryPipeline._normalize_text(drug_name)

        for match in matches:
            if DrugRegistryPipeline._normalize_text(match.get("hebrew_name", "")) == normalized_query:
                return match, "exact_hebrew_name"

        for match in matches:
            if DrugRegistryPipeline._normalize_text(match.get("english_name", "")) == normalized_query:
                return match, "exact_english_name"

        return matches[0], "first_result"

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.strip().lower().split())

    @classmethod
    def _tokenize_text(cls, value: str) -> list[str]:
        normalized = cls._normalize_text(value)
        return re.findall(r"[a-z0-9א-ת]+", normalized)

    @classmethod
    def _is_relevant_autocomplete_candidate(cls, *, row: PipelineInputRow, candidate: str) -> bool:
        candidate_tokens = cls._tokenize_text(candidate)
        if not candidate_tokens:
            return False

        source_values = [row.english_name, row.hebrew_name, row.input_drug_name]
        source_tokens = [token for value in source_values for token in cls._tokenize_text(value)]
        if not source_tokens:
            return True

        for source_token in source_tokens:
            for candidate_token in candidate_tokens:
                if source_token == candidate_token:
                    return True
                if candidate_token.startswith(source_token) or candidate_token.endswith(source_token):
                    return True
                if source_token.startswith(candidate_token) and len(candidate_token) >= 6:
                    return True

        return False

    @classmethod
    def _clean_input_value(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        cleaned = re.sub(r"^[^A-Za-zא-ת0-9]+", "", cleaned)
        cleaned = re.sub(r"\([^)]*\)\s*$", "", cleaned).strip()
        cleaned = re.sub(r"\([^)]*$", "", cleaned).strip()
        cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned).strip()
        cleaned = re.sub(r"[^A-Za-zא-ת0-9]+$", "", cleaned).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned
