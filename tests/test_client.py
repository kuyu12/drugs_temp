from unittest.mock import patch

import pytest
import requests

from moh_medical_devices.client import Client, Config, RegistryError, search_payload


class Response:
    def __init__(self, data, status=200, content_type="application/json", **headers):
        self.data = data
        self.status_code = status
        self.headers = {"Content-Type": content_type, **headers}
    def json(self):
        return self.data


def envelope(data):
    return Response({"statusCode": 200, "returnObject": data})


def test_search_contract_uses_source_spellings_and_zero_based_page():
    response = envelope({"totalRows": 0, "pageNumber": 0, "medicalAccessoriesList": []})
    with patch("requests.Session.post", return_value=response) as call:
        Client(Config(delay_seconds=0)).search()
    assert call.call_args.args[0].endswith("/GetMedicalDevicesDataWithParam")
    assert call.call_args.kwargs["json"] == search_payload()
    assert call.call_args.kwargs["json"]["maxResaults"] == 1000
    assert call.call_args.kwargs["json"]["pageNumber"] == 0


def test_detail_number_is_numeric_and_total_zero_is_not_empty():
    value = {"totalRows": 0, "medicalAccessoriesList": [{"registrationNumber": "25320001"}]}
    with patch("requests.Session.post", return_value=envelope(value)) as call:
        assert Client(Config(delay_seconds=0)).details("25320001")["returnObject"] == value
    number = call.call_args.kwargs["json"]["registrationNumber"]
    assert type(number) is int and number == 25320001


@pytest.mark.parametrize("response", [
    Response({}, content_type="text/html"), Response({}, status=403),
    Response({"statusCode": 500, "returnObject": {}}),
    Response({"statusCode": 200, "returnObject": None}),
])
def test_denials_and_errors_are_not_empty_successes(response):
    with patch("requests.Session.post", return_value=response) as call:
        with pytest.raises(RegistryError):
            Client(Config(delay_seconds=0)).search()
    assert call.call_count == 1


def test_rate_limit_retry_and_retry_after():
    with patch("requests.Session.post", side_effect=[Response({}, status=429, **{"Retry-After": "2"}),
               envelope({"totalRows": 0, "pageNumber": 0, "medicalAccessoriesList": []})]) as call:
        with patch("time.sleep") as sleep:
            Client(Config(delay_seconds=0)).search()
    assert call.call_count == 2
    assert any(c.args == (2.0,) for c in sleep.call_args_list)


def test_transport_failure_retries_with_finite_budget():
    with patch("requests.Session.post", side_effect=requests.Timeout) as call, patch("time.sleep"):
        with pytest.raises(RegistryError):
            Client(Config(delay_seconds=0, attempts=2)).search()
    assert call.call_count == 2


def test_detail_identity_mismatch_is_rejected():
    with patch("requests.Session.post", return_value=envelope({"medicalAccessoriesList": [{"registrationNumber": "999"}]})):
        with pytest.raises(RegistryError):
            Client(Config(delay_seconds=0)).details("123")


def test_filter_options_use_correct_filter_field():
    with patch("requests.Session.post", return_value=envelope([{"key": 10087, "name": "DISCOVER"}])) as call:
        Client(Config(delay_seconds=0)).filter_options("manufacturer", "DISCOVER")
    assert call.call_args.kwargs["json"]["manufacter"] == "DISCOVER"
