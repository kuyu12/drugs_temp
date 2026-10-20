import json
from pathlib import Path

import pytest

import moh_medical_devices
from moh_medical_devices import fetch_medical_devices_dataframe
from moh_medical_devices.record_normalization import normalize


def test_public_function_is_exported_from_the_delivered_module():
    assert moh_medical_devices.__version__ == "0.2.0"
    assert fetch_medical_devices_dataframe.__module__ == "moh_medical_devices.pandas_ingestion"
    package = Path(moh_medical_devices.__file__).parent
    assert (package / "pandas_ingestion.py").is_file()
    assert not (package / "table.py").exists()
    assert not (package / "pipeline.py").exists()


def test_notebook_identifies_an_incomplete_checkout_before_network(monkeypatch, tmp_path):
    notebook_path = Path(__file__).resolve().parents[1] / "notebooks/medical_devices_ingestion.ipynb"
    notebook = json.loads(notebook_path.read_text())
    configuration = next(c["source"] for c in notebook["cells"] if c["id"] == "configuration")
    package = tmp_path / "src/moh_medical_devices"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="pandas_ingestion.py"):
        exec(configuration, {})


@pytest.mark.parametrize("raw, expected", [("12/31/2026", "2026-12-31"), ("invalid", None), (None, None)])
def test_normalization_preserves_registration_and_original_date(raw, expected):
    row = normalize({"registrationNumber": "000123", "experationDate": raw}, "run", 0, 0, "now")
    assert row["registration_number"] == "000123"
    assert row["expiration_date_raw"] == raw
    assert row["expiration_date"] == expected
