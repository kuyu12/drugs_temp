import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from moh_medical_devices.client import RegistryError
from moh_medical_devices.pandas_ingestion import fetch_medical_devices_dataframe


class Client:
    config = SimpleNamespace(base_url="https://example.test/api")

    def __init__(self):
        self.rows = [{"registrationNumber": str(i // 2 + 1), "eProductName": str(i),
                      "experationDate": "12/31/2026", "future": {"nested": [i]}}
                     for i in range(5)]
        self.pages, self.detail_calls = [], []

    def search(self, page, size, search, declaration):
        self.pages.append(page)
        return {"returnObject": {"pageNumber": page, "totalRows": len(self.rows),
                "medicalAccessoriesList": self.rows[page * size:(page + 1) * size]}}

    def details(self, number):
        self.detail_calls.append(number)
        return {"statusCode": 200, "returnObject": {"totalRows": 0, "medicalAccessoriesList": [
            {"registrationNumber": number, "extension": [1, 2]},
            {"registrationNumber": number, "extension": [3]},
        ]}}


def test_full_dataframe_preserves_rows_extensions_and_does_not_write(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = Client()
    frame = fetch_medical_devices_dataframe(client, page_size=2)
    assert isinstance(frame, pd.DataFrame) and len(frame) == 5
    assert client.pages == [0, 1, 2, 0]
    assert client.detail_calls == ["1", "2", "3"]
    assert frame["registration_number"].tolist() == ["1", "1", "2", "2", "3"]
    assert frame.iloc[0]["future"] == {"nested": [0]}
    assert json.loads(frame.iloc[0]["raw_json"])["future"] == {"nested": [0]}
    assert len(frame.iloc[0]["details"]) == 2
    assert json.loads(frame.iloc[0]["details_raw_json"])["returnObject"]["totalRows"] == 0
    assert frame.iloc[0]["expiration_date"] == pd.Timestamp("2026-12-31")
    assert frame.attrs["extraction"]["status"] == "complete"
    assert frame.attrs["extraction"]["detail_requests"] == 3
    assert list(tmp_path.iterdir()) == []


def test_details_can_be_disabled():
    client = Client()
    frame = fetch_medical_devices_dataframe(client, page_size=2, include_details=False)
    assert client.detail_calls == []
    assert frame["details"].isna().all()
    assert frame.attrs["extraction"]["include_details"] is False


def test_detail_failure_never_returns_partial_success():
    class Failed(Client):
        def details(self, number):
            raise RegistryError("Detail access failed")
    with pytest.raises(RegistryError, match="Detail access"):
        fetch_medical_devices_dataframe(Failed(), page_size=2)


@pytest.mark.parametrize("problem", ["short", "repeated", "count", "head", "page"])
def test_inconsistent_source_is_rejected(problem):
    class Changed(Client):
        def search(self, page, *args):
            result = super().search(page, *args)
            data = result["returnObject"]
            if page == 1:
                if problem == "short": data["medicalAccessoriesList"] = []
                if problem == "repeated": data["medicalAccessoriesList"] = self.rows[:2]
                if problem == "count": data["totalRows"] += 1
                if problem == "page": data["pageNumber"] = 0
            if problem == "head" and len(self.pages) > 1 and page == 0:
                data["medicalAccessoriesList"] = [{**r, "changed": True} for r in self.rows[:2]]
            return result
    with pytest.raises(RegistryError):
        fetch_medical_devices_dataframe(Changed(), page_size=2, include_details=False)


def test_empty_registry_returns_a_complete_empty_dataframe():
    client = Client()
    client.rows = []
    frame = fetch_medical_devices_dataframe(client)
    assert frame.empty and "registration_number" in frame and "details" in frame
    assert frame.attrs["extraction"]["rows"] == 0
    assert client.detail_calls == []


def test_invalid_date_and_leading_zeros_are_preserved():
    client = Client()
    client.rows = [{"registrationNumber": "000123", "experationDate": "invalid"}]
    frame = fetch_medical_devices_dataframe(client, include_details=False)
    assert frame.iloc[0]["registration_number"] == "000123"
    assert frame.iloc[0]["expiration_date_raw"] == "invalid"
    assert pd.isna(frame.iloc[0]["expiration_date"])


def test_notebook_runs_with_pandas_without_spark_volumes_or_file_output(monkeypatch):
    import moh_medical_devices

    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "notebooks/medical_devices_ingestion.ipynb").read_text())
    client = Client()
    closed = []
    client.close = lambda: closed.append(True)
    monkeypatch.setattr(moh_medical_devices, "MedicalDevicesClient", lambda config: client)
    monkeypatch.chdir(root / "notebooks")
    shown = []
    namespace = {"display": shown.append}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code" and not cell["source"].startswith("%"):
            exec(compile(cell["source"], "notebook", "exec"), namespace)
            if cell["id"] == "configuration":
                assert namespace["detail_workers"] == 4
                namespace["detail_workers"] = 1  # This fake tests the notebook's sequential fallback.
    assert isinstance(namespace["devices_df"], pd.DataFrame)
    assert len(namespace["devices_df"]) == 5
    assert len(shown) == 1 and closed == [True]
    assert client.detail_calls == ["1", "2", "3"]
