"""Arranque del proxy WireGuard opcional, limitado a localhost."""

import json
import os
import socket
import subprocess
from pathlib import Path
from time import monotonic, sleep


def start_proxy(configuration: str, directory: Path) -> subprocess.Popen:
    try:
        config = json.loads(configuration)
        inbounds = config["inbounds"]
        if len(inbounds) != 1 or inbounds[0].get("listen") != "127.0.0.1":
            raise ValueError
        if inbounds[0].get("listen_port") != 40000:
            raise ValueError
        config["log"] = {"disabled": True}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("Configuración del proxy local no válida.") from None
    config_file = directory / "network-proxy.json"
    config_file.touch(mode=0o600)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    validation = subprocess.run(
        ["sing-box", "check", "-c", str(config_file)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=15, check=False,
    )
    if validation.returncode:
        raise RuntimeError("Configuración del proxy local no válida.")
    return subprocess.Popen(
        ["sing-box", "run", "-c", str(config_file)],
        env={**os.environ, "GOMEMLIMIT": "40MiB"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_for_proxy(process: subprocess.Popen, timeout: float = 15) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("El proxy local terminó durante el arranque.")
        try:
            with socket.create_connection(("127.0.0.1", 40000), timeout=1):
                return
        except OSError:
            sleep(0.5)
    raise RuntimeError("El proxy local agotó el tiempo de arranque.")
