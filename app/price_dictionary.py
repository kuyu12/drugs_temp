import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PriceDictionaryEntry:
    drug_name: str
    code: str
    source_file: str
    normalized_name: str


class PriceDictionary:
    def __init__(self, entries: list[PriceDictionaryEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_csv(cls, path: Path) -> "PriceDictionary":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            entries = [
                PriceDictionaryEntry(
                    drug_name=(row.get("drug_name") or "").strip(),
                    code=(row.get("code") or "").strip(),
                    source_file=(row.get("source_file") or "").strip(),
                    normalized_name=cls.normalize((row.get("drug_name") or "").strip()),
                )
                for row in reader
                if (row.get("drug_name") or "").strip()
            ]
        return cls(entries)

    def find_best_match(self, *candidates: str) -> tuple[PriceDictionaryEntry | None, str]:
        matches = self.find_candidate_matches(*candidates, max_results=1)
        if not matches:
            return None, ""
        return matches[0]

    def find_candidate_matches(
        self,
        *candidates: str,
        max_results: int = 10,
    ) -> list[tuple[PriceDictionaryEntry, str]]:
        normalized_candidates = [self.normalize(value) for value in candidates if self.normalize(value)]
        if not normalized_candidates:
            return []

        ranked_by_entry: dict[tuple[str, str], tuple[int, PriceDictionaryEntry, str]] = {}

        for candidate in normalized_candidates:
            for entry in self.entries:
                if entry.normalized_name == candidate:
                    key = (entry.drug_name, entry.code)
                    current = ranked_by_entry.get(key)
                    if current is None or 0 < current[0]:
                        ranked_by_entry[key] = (0, entry, "dictionary_exact")

        for candidate in normalized_candidates:
            for entry in self.entries:
                if candidate in entry.normalized_name or entry.normalized_name in candidate:
                    key = (entry.drug_name, entry.code)
                    current = ranked_by_entry.get(key)
                    if current is None or 1 < current[0]:
                        ranked_by_entry[key] = (1, entry, "dictionary_contains")

        for candidate in normalized_candidates:
            candidate_tokens = set(candidate.split())
            if not candidate_tokens:
                continue
            for entry in self.entries:
                entry_tokens = set(entry.normalized_name.split())
                if candidate_tokens & entry_tokens:
                    key = (entry.drug_name, entry.code)
                    current = ranked_by_entry.get(key)
                    if current is None or 2 < current[0]:
                        ranked_by_entry[key] = (2, entry, "dictionary_token_overlap")

        ranked = list(ranked_by_entry.values())
        ranked.sort(key=lambda item: (item[0], len(item[1].drug_name), item[1].drug_name))
        return [(entry, strategy) for _, entry, strategy in ranked[:max_results]]

    @staticmethod
    def normalize(value: str) -> str:
        return " ".join(value.strip().lower().replace("-", " ").replace("/", " ").split())
