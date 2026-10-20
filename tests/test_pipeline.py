import json
from types import SimpleNamespace

import pytest

from moh_medical_devices.client import Config, RegistryError
from moh_medical_devices.pipeline import normalize, run_snapshot
from moh_medical_devices.table import prepare_dataframe, table_ddl


class FakeClient:
    config = Config(delay_seconds=0)

    def __init__(self):
        self.calls = []
        self.rows = [{"registrationNumber": "000123" if i < 2 else str(100 + i),
                      "hProductName": f"Device {i}", "experationDate": "12/31/2026",
                      "future_field": {"nested": [i]}} for i in range(5)]

    def search(self, page, size, search, declaration):
        self.calls.append(page)
        return {"statusCode": 200, "returnObject": {"pageNumber": page, "totalRows": len(self.rows),
                "medicalAccessoriesList": self.rows[page * size:(page + 1) * size]}}


def test_full_snapshot_preserves_fields_duplicate_registrations_and_resume(tmp_path):
    client = FakeClient()
    m = run_snapshot(client, str(tmp_path), "full", page_size=2)
    assert m["status"] == "complete" and m["rows"] == 5 and m["unique_registration_numbers"] == 4
    rows = [json.loads(line) for line in (tmp_path / "full/records.jsonl").read_text().splitlines()]
    assert rows[0]["registration_number"] == "000123"
    assert json.loads(rows[0]["raw_json"])["future_field"] == {"nested": [0]}
    assert rows[0]["expiration_date"] == "2026-12-31"
    client.calls.clear()
    run_snapshot(client, str(tmp_path), "full", page_size=2)
    assert client.calls == [0, 0]


def test_sample_cannot_prepare_table(tmp_path):
    m = run_snapshot(FakeClient(), str(tmp_path), "sample", page_size=2, max_pages=1)
    assert m["status"] == "sampled" and m["rows"] == 2
    with pytest.raises(ValueError, match="complete"):
        prepare_dataframe(None, str(tmp_path / "sample"))


def test_short_page_fails_closed(tmp_path):
    class ShortClient(FakeClient):
        def search(self, *args):
            result = super().search(*args)
            result["returnObject"]["medicalAccessoriesList"] = []
            return result
    with pytest.raises(RegistryError, match="length"):
        run_snapshot(ShortClient(), str(tmp_path), "short", page_size=2)
    assert json.loads((tmp_path / "short/manifest.json").read_text())["status"] == "failed"


def test_repeated_page_is_rejected(tmp_path):
    class RepeatClient(FakeClient):
        def search(self, page, size, *args):
            result = super().search(page, size, *args)
            result["returnObject"]["medicalAccessoriesList"] = self.rows[:size]
            return result
    with pytest.raises(RegistryError, match="Repeated"):
        run_snapshot(RepeatClient(), str(tmp_path), "repeat", page_size=2)


def test_source_count_change_is_rejected(tmp_path):
    class ChangedClient(FakeClient):
        def search(self, page, *args):
            result = super().search(page, *args)
            if page:
                result["returnObject"]["totalRows"] += 1
            return result
    with pytest.raises(RegistryError, match="total changed"):
        run_snapshot(ChangedClient(), str(tmp_path), "changed", page_size=2)


def test_new_filters_cannot_reuse_old_pages(tmp_path):
    client = FakeClient()
    run_snapshot(client, str(tmp_path), "same", page_size=2)
    with pytest.raises(ValueError, match="parameters changed"):
        run_snapshot(client, str(tmp_path), "same", page_size=2, search="other")


def test_source_head_change_blocks_resume(tmp_path):
    client = FakeClient()
    run_snapshot(client, str(tmp_path), "same", page_size=2)
    client.rows[0] = {**client.rows[0], "hProductName": "changed"}
    with pytest.raises(RegistryError, match="head changed"):
        run_snapshot(client, str(tmp_path), "same", page_size=2)


def test_checksum_protects_table_preparation(tmp_path):
    run_snapshot(FakeClient(), str(tmp_path), "good", page_size=2)
    (tmp_path / "good/records.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="checksum"):
        prepare_dataframe(None, str(tmp_path / "good"))


def test_dataframe_preparation_uses_explicit_schema_and_no_table_operations(tmp_path):
    run_snapshot(FakeClient(), str(tmp_path), "good", page_size=2)
    class Reader:
        def schema(self, value):
            assert "registration_number` STRING" in value
            return self
        def option(self, *args):
            return self
        def json(self, filename):
            return SimpleNamespace(count=lambda: 5)
    frame = prepare_dataframe(SimpleNamespace(read=Reader()), str(tmp_path / "good"))
    assert frame.count() == 5


@pytest.mark.parametrize("name", ["table", "a.b", "a.b.c;DROP TABLE x", "a.b.c.d"])
def test_table_identifiers_are_validated(name):
    with pytest.raises(ValueError):
        table_ddl(name)


def test_table_ddl_is_preparation_only():
    ddl = table_ddl("catalog.schema.devices")
    assert "USING DELTA" in ddl and "PARTITIONED BY (run_id)" in ddl


def test_invalid_date_remains_unknown_without_losing_original():
    row = normalize({"registrationNumber": "1", "experationDate": "invalid"}, "run", 0, 0, "now")
    assert row["expiration_date"] is None and row["expiration_date_raw"] == "invalid"
