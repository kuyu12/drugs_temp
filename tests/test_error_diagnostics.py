import json
from pathlib import Path
from types import SimpleNamespace
import traceback
from unittest.mock import patch

import pytest
import requests

from moh_medical_devices.client import Client, Config, RegistryError
from moh_medical_devices.pandas_ingestion import fetch_medical_devices_dataframe
from test_dataframe import Client as FakeClient


def response(status, body, content_type="application/json"):
    value = requests.Response()
    value.status_code = status
    value._content = body.encode()
    value.encoding = "utf-8"
    value.headers["Content-Type"] = content_type
    value.url = "https://registries.health.gov.il/api/MedicalDevices/test"
    return value


@pytest.mark.parametrize("status", [403, 429, 502])
def test_http_failure_preserves_original_http_error_and_full_body(status):
    body = "UPSTREAM_START\n" + "x" * 6000 + "\nUPSTREAM_END"
    upstream = response(status, body)
    client = Client(Config(delay_seconds=0, attempts=2))
    try:
        with patch("requests.Session.post", return_value=upstream) as post, patch("time.sleep"):
            with pytest.raises(RegistryError) as failure:
                client.search()
        error = failure.value
        text = "".join(traceback.format_exception(error))
        assert isinstance(error.__cause__, requests.HTTPError)
        assert error.__cause__.response is upstream and error.response is upstream
        assert body in text and "POST https://registries.health.gov.il" in text
        assert post.call_count == (1 if status == 403 else 2)
    finally:
        client.close()


@pytest.mark.parametrize("body, content_type", [
    ("<html>Original denial detail</html>", "text/html"),
    ('{"statusCode":500,"message":"Original application failure"}', "application/json"),
    ('{"statusCode":200}', "application/json"),
])
def test_response_errors_keep_the_entire_upstream_response(body, content_type):
    upstream = response(200, body, content_type)
    client = Client(Config(delay_seconds=0))
    try:
        with patch("requests.Session.post", return_value=upstream):
            with pytest.raises(RegistryError) as failure:
                client.search()
        assert failure.value.response is upstream
        assert body in "".join(traceback.format_exception(failure.value))
    finally:
        client.close()


def test_json_parse_error_retains_original_decoder_exception():
    client = Client(Config(delay_seconds=0))
    try:
        with patch("requests.Session.post", return_value=response(200, "invalid original JSON")):
            with pytest.raises(RegistryError) as failure:
                client.search()
        assert isinstance(failure.value.__cause__, requests.exceptions.JSONDecodeError)
        assert "invalid original JSON" in "".join(traceback.format_exception(failure.value))
    finally:
        client.close()


def test_transport_error_keeps_original_exception_identity_and_nested_cause():
    original = requests.Timeout("Original timeout detail")
    original.__cause__ = OSError("Original socket detail")
    client = Client(Config(delay_seconds=0, attempts=2))
    try:
        with patch("requests.Session.post", side_effect=original), patch("time.sleep"):
            with pytest.raises(RegistryError) as failure:
                client.search()
        assert failure.value.__cause__ is original
        text = "".join(traceback.format_exception(failure.value))
        assert "Original socket detail" in text and "Original timeout detail" in text
        assert "attempt 2/2" in text
    finally:
        client.close()


def test_worker_propagates_the_same_exception_and_identifies_registration():
    original = requests.Timeout("Original worker traceback detail")

    class FailedClient(FakeClient):
        def fork(self, limiter):
            def fail(number):
                raise original
            return SimpleNamespace(details=fail, close=lambda: None)

    client = FailedClient()
    client.rows = [{"registrationNumber": "123"}]
    with pytest.raises(requests.Timeout) as failure:
        fetch_medical_devices_dataframe(client, detail_workers=2)
    assert failure.value is original
    text = "".join(traceback.format_exception(failure.value))
    assert "registration_number=123" in text and "in fail" in text


def test_notebook_prints_full_chain_keeps_original_object_and_reraises(capsys):
    notebook = json.loads((Path(__file__).resolve().parents[1] / "notebooks/medical_devices_ingestion.ipynb").read_text())
    source = next(c["source"] for c in notebook["cells"] if c["id"] == "extract")
    cause = requests.Timeout("ORIGINAL_EXCEPTION_DETAIL_" + "x" * 6000 + "_END")
    closed = []
    observed = []

    def fail(*args, **kwargs):
        try:
            raise cause
        except requests.Timeout as exc:
            error = RegistryError("Final API failure")
            observed.append(error)
            raise error from exc

    namespace = {
        "MedicalDevicesClient": lambda config: SimpleNamespace(close=lambda: closed.append(True)),
        "MedicalDevicesConfig": lambda **kwargs: None,
        "fetch_medical_devices_dataframe": fail,
        "delay_seconds": 0, "page_size": 1000, "include_details": True,
        "search": "", "declaration_only": False, "detail_workers": 4,
        "requests_per_second": 2, "devices_df": "stale result",
    }
    with pytest.raises(RegistryError) as failure:
        exec(compile(source, "notebook", "exec"), namespace)
    assert failure.value is observed[0] and namespace["last_error"] is failure.value
    assert namespace["last_error"].__cause__ is cause
    assert namespace["devices_df"] is None and closed == [True]
    assert str(cause) in namespace["last_error_traceback"]
    assert namespace["last_error_traceback"] in capsys.readouterr().err
