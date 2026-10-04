"""Supervisa el proveedor PO Token local y el comando del contenedor."""

import os
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from app.network_proxy import start_proxy, wait_for_proxy

PROVIDER_URL = "http://127.0.0.1:4416"


def wait_for_provider(provider: subprocess.Popen, timeout: float = 120) -> None:
    """Espera el arranque una sola vez, sin el límite de 15 s del plugin script."""
    deadline = monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while monotonic() < deadline:
        if provider.poll() is not None:
            raise RuntimeError("El proveedor PO Token terminó durante el arranque.")
        try:
            with opener.open(PROVIDER_URL + "/ping", timeout=2):
                return
        except (URLError, TimeoutError):
            sleep(0.5)
    raise RuntimeError("El proveedor PO Token no arrancó en el tiempo previsto.")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    command = sys.argv[1:]
    if not command:
        raise SystemExit("Falta el comando principal del contenedor.")
    server_home = os.environ.get("VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_SERVER_HOME")
    base_url = os.environ.get("VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_BASE_URL")
    provider_mode = os.environ.get("VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_MODE", "http")
    warp_config = os.environ.get("VIDEO_TRANSCRIBER_YOUTUBE_WARP_CONFIG")
    local_provider = bool(
        server_home and base_url == PROVIDER_URL and provider_mode == "http"
    )
    if not local_provider and not warp_config:
        os.execvp(command[0], command)
    provider = None
    network_proxy = None
    application = None
    directory = TemporaryDirectory(prefix="video-transcriber-proxy-")

    def shutdown(signum, frame):
        if application is not None:
            stop_process(application)
        if provider is not None:
            stop_process(provider)
        if network_proxy is not None:
            stop_process(network_proxy)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        if warp_config:
            network_proxy = start_proxy(warp_config, Path(directory.name))
            wait_for_proxy(network_proxy)
            print("youtube_warp_proxy_ready", flush=True)
        if local_provider:
            provider = subprocess.Popen(
                ["node", "--max-old-space-size=128",
                 str(Path(server_home) / "build/main.js"),
                 "--host", "127.0.0.1", "--port", "4416"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            wait_for_provider(provider)
            print("youtube_po_token_provider_ready", flush=True)
        application = subprocess.Popen(command)
        while application.poll() is None:
            if provider is not None and provider.poll() is not None:
                print("youtube_po_token_provider_exited", flush=True)
                return 1
            if network_proxy is not None and network_proxy.poll() is not None:
                print("youtube_warp_proxy_exited", flush=True)
                return 1
            sleep(0.5)
        return application.returncode
    except RuntimeError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        if application is not None:
            stop_process(application)
        if provider is not None:
            stop_process(provider)
        if network_proxy is not None:
            stop_process(network_proxy)
        directory.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
