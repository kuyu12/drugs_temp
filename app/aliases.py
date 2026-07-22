import csv
from pathlib import Path


class DrugAliases:
    def __init__(self, aliases_by_key: dict[str, list[str]]) -> None:
        self.aliases_by_key = aliases_by_key

    @classmethod
    def from_csv(cls, path: Path) -> "DrugAliases":
        aliases_by_key: dict[str, list[str]] = {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                drug_name = cls.normalize((row.get("drug_name") or "").strip())
                alias = (row.get("alias") or "").strip()
                if not drug_name or not alias:
                    continue
                aliases_by_key.setdefault(drug_name, [])
                if alias not in aliases_by_key[drug_name]:
                    aliases_by_key[drug_name].append(alias)
        return cls(aliases_by_key)

    def lookup(self, *values: str) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self.normalize(value)
            if not normalized:
                continue
            for alias in self.aliases_by_key.get(normalized, []):
                if alias not in seen:
                    seen.add(alias)
                    results.append(alias)
        return results

    @staticmethod
    def normalize(value: str) -> str:
        return " ".join(value.strip().lower().split())
