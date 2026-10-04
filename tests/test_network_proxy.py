from unittest.mock import Mock

import pytest

from app import network_proxy


@pytest.mark.parametrize("configuration", [
    "private-secret", '{"inbounds":[]}',
    '{"inbounds":[{"listen":"0.0.0.0","listen_port":40000}]}',
])
def test_proxy_rejects_public_listener_without_logging_secret(configuration, tmp_path):
    with pytest.raises(RuntimeError) as caught:
        network_proxy.start_proxy(configuration, tmp_path)
    assert "private-secret" not in str(caught.value)
    assert not list(tmp_path.iterdir())


def test_proxy_configuration_is_private_and_process_logs_are_hidden(
    monkeypatch, tmp_path,
):
    configuration = '{"inbounds":[{"listen":"127.0.0.1","listen_port":40000}]}'
    monkeypatch.setattr(network_proxy.subprocess, "run", lambda *a, **k: Mock(
        returncode=0,
    ))
    factory = Mock()
    monkeypatch.setattr(network_proxy.subprocess, "Popen", factory)
    network_proxy.start_proxy(configuration, tmp_path)
    assert factory.call_args.kwargs["stderr"] == network_proxy.subprocess.DEVNULL
    assert factory.call_args.kwargs["stdout"] == network_proxy.subprocess.DEVNULL
    assert '"disabled": true' in (tmp_path / "network-proxy.json").read_text()


def test_proxy_startup_detects_crashed_process():
    process = Mock()
    process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="terminó durante el arranque"):
        network_proxy.wait_for_proxy(process)
