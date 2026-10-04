import subprocess
from contextlib import nullcontext
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from app import container_entrypoint


def test_wait_for_provider_allows_slow_start_and_checks_ping(monkeypatch):
    provider = Mock()
    provider.poll.return_value = None
    opener = Mock()
    opener.open.side_effect = [URLError("starting"), nullcontext()]
    monkeypatch.setattr(container_entrypoint, "build_opener", lambda *args: opener)
    monkeypatch.setattr(container_entrypoint, "sleep", lambda duration: None)

    container_entrypoint.wait_for_provider(provider)
    assert opener.open.call_count == 2
    assert opener.open.call_args.args[0] == "http://127.0.0.1:4416/ping"


def test_wait_for_provider_stops_if_process_crashes():
    provider = Mock()
    provider.poll.return_value = 1
    with pytest.raises(RuntimeError, match="terminó durante el arranque"):
        container_entrypoint.wait_for_provider(provider)


def test_provider_startup_timeout_is_bounded(monkeypatch):
    provider = Mock()
    provider.poll.return_value = None
    opener = Mock()
    opener.open.side_effect = URLError("starting")
    clock = iter([0, 0, 121])
    monkeypatch.setattr(container_entrypoint, "monotonic", lambda: next(clock))
    monkeypatch.setattr(container_entrypoint, "build_opener", lambda *args: opener)
    monkeypatch.setattr(container_entrypoint, "sleep", lambda duration: None)
    with pytest.raises(RuntimeError, match="tiempo previsto"):
        container_entrypoint.wait_for_provider(provider)


def test_cleanup_kills_provider_that_ignores_shutdown():
    provider = Mock()
    provider.poll.return_value = None
    provider.wait.side_effect = [subprocess.TimeoutExpired("node", 5), 0]
    container_entrypoint.stop_process(provider)
    provider.terminate.assert_called_once()
    provider.kill.assert_called_once()
