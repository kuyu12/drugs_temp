from concurrent.futures import ThreadPoolExecutor
from threading import Lock, get_ident
import time
from unittest.mock import Mock, patch

import pytest

from moh_medical_devices.client import Client, Config, RegistryError, RequestLimiter
from moh_medical_devices.pandas_ingestion import fetch_medical_devices_dataframe
from test_dataframe import Client as FakeClient


class ParallelClient(FakeClient):
    def __init__(self, fail=False):
        super().__init__()
        self.lock, self.created, self.started = Lock(), [], []
        self.active = self.peak = 0
        self.fail = fail

    def fork(self, limiter):
        parent = self

        class Worker:
            owner = get_ident()
            closed = False

            def details(self, number):
                assert get_ident() == self.owner
                limiter.wait()
                with parent.lock:
                    parent.started.append(time.monotonic())
                    parent.active += 1
                    parent.peak = max(parent.peak, parent.active)
                try:
                    if parent.fail:
                        raise RegistryError("HTTP 403: details")
                    time.sleep(0.5 if number == "1" else 0.3)
                    return parent.details(number)
                finally:
                    with parent.lock:
                        parent.active -= 1

            def close(self):
                self.closed = True

        worker = Worker()
        with self.lock:
            self.created.append(worker)
        return worker


def test_parallel_details_are_bounded_paced_isolated_and_keep_source_order():
    client = ParallelClient()
    frame = fetch_medical_devices_dataframe(client, page_size=2, detail_workers=2, requests_per_second=5)
    assert frame["registration_number"].tolist() == ["1", "1", "2", "2", "3"]
    assert sorted(client.detail_calls) == ["1", "2", "3"]
    assert client.peak == 2 and len(client.created) == 2
    assert all(worker.closed for worker in client.created)
    assert all(b - a >= 0.18 for a, b in zip(client.started, client.started[1:]))
    for _, row in frame.iterrows():
        assert row["details"][0]["registrationNumber"] == row["registration_number"]


def test_failure_stops_new_work_closes_workers_and_never_returns_partial_frame():
    client = ParallelClient(fail=True)
    client.rows = [{"registrationNumber": str(i)} for i in range(1, 101)]
    with pytest.raises(RegistryError, match="403"):
        fetch_medical_devices_dataframe(client, detail_workers=2, requests_per_second=5)
    assert len(client.started) <= 2
    assert all(worker.closed for worker in client.created)


@pytest.mark.parametrize("settings", [
    {"detail_workers": 0}, {"detail_workers": 9}, {"detail_workers": True},
    {"requests_per_second": 0}, {"requests_per_second": 6},
    {"requests_per_second": float("nan")}, {"requests_per_second": True},
])
def test_invalid_parallel_settings_fail_before_network(settings):
    client = FakeClient()
    with pytest.raises(ValueError):
        fetch_medical_devices_dataframe(client, **settings)
    assert client.pages == []


def test_shared_cooldown_delays_other_threads_and_stop_cancels_wait():
    limiter = RequestLimiter(5)
    limiter.defer(0.08)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        timestamps = sorted(pool.map(lambda _: (limiter.wait(), time.monotonic())[1], range(2)))
    assert timestamps[0] - started >= 0.06
    assert timestamps[1] - timestamps[0] >= 0.18
    limiter.stop()
    with pytest.raises(RegistryError, match="cancelled"):
        limiter.wait()


def test_worker_sessions_are_independent_and_preserve_timing_config():
    client = Client(Config(timeout_seconds=12, delay_seconds=2, attempts=2))
    worker = client.fork(RequestLimiter(2))
    try:
        assert worker.session is not client.session
        assert worker.config.delay_seconds == 0
        assert worker.config.timeout_seconds == 12 and worker.config.attempts == 2
        assert worker.config.base_url == client.config.base_url
    finally:
        worker.close()
        client.close()


def test_retry_after_updates_shared_limiter_before_retry():
    limiter = Mock()
    throttled = Mock(status_code=429, headers={"Retry-After": "2"})
    success = Mock(status_code=200, headers={"Content-Type": "application/json"})
    success.json.return_value = {"statusCode": 200, "returnObject": {}}
    with patch("requests.Session.post", side_effect=[throttled, success]):
        client = Client(Config(delay_seconds=0), limiter=limiter)
        try:
            client.post("details", {})
        finally:
            client.close()
    limiter.defer.assert_called_once_with(2.0)
    assert limiter.wait.call_count == 2
