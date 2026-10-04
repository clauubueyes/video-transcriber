"""Contexto yt-dlp con una copia temporal de las cookies del servidor."""

import logging
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadError

from app.core.config import Settings

logger = logging.getLogger("video_transcriber.ytdlp")


def _redact(message: str, proxy: str | None) -> str:
    if proxy:
        message = message.replace(proxy, "[proxy]")
    return re.sub(r"(https?|socks\w*)://[^\s/@]+@", r"\1://[redacted]@", message)


class _ProviderLogger:
    def __init__(self, proxy: str | None) -> None:
        self._proxy = proxy

    def debug(self, message: str) -> None:
        # yt-dlp también envía mensajes informativos a debug(). No registrar
        # trazas detalladas, identificadores de sesión ni valores de los tokens.
        match = re.search(
            r"Generating a (gvs|player|subs) PO Token for ([a-z_]+) client", message,
        )
        if match:
            logger.info(
                "youtube_po_token_requested: context=%s client=%s", *match.groups(),
            )

    def warning(self, message: str) -> None:
        logger.warning("youtube_provider_warning: %s", _redact(message, self._proxy))

    def error(self, message: str) -> None:
        logger.error("youtube_provider_error: %s", _redact(message, self._proxy))


def youtube_download_options(settings: Settings) -> dict[str, Any]:
    """Comparte cliente, proveedor POT y salida de red en API y worker."""
    options: dict[str, Any] = {}
    extractor_args: dict[str, Any] = {}
    base_url = (
        settings.youtube_po_token_base_url
        if settings.youtube_po_token_mode == "http" else None
    )
    if settings.youtube_js_runtimes:
        runtimes = [
            value.strip().lower()
            for value in settings.youtube_js_runtimes.split(",") if value.strip()
        ]
        if set(runtimes) - {"deno", "node", "bun", "quickjs"}:
            raise ValueError("Runtime JavaScript de YouTube no reconocido.")
        options["js_runtimes"] = {value: {} for value in runtimes}
    if settings.youtube_player_clients:
        clients = [
            client.strip() for client in settings.youtube_player_clients.split(",")
            if client.strip()
        ]
        if clients:
            extractor_args["youtube"] = {"player_client": clients}
    if base_url or settings.youtube_po_token_server_home:
        extractor_args.setdefault("youtube", {})["fetch_pot"] = [
            settings.youtube_po_token_policy,
        ]
    if base_url:
        extractor_args["youtubepot-bgutilhttp"] = {
            "base_url": [base_url],
        }
    elif settings.youtube_po_token_server_home:
        extractor_args["youtubepot-bgutilscript"] = {
            "server_home": [str(settings.youtube_po_token_server_home)],
        }
    if extractor_args:
        options["extractor_args"] = extractor_args
    if settings.youtube_impersonate:
        options["impersonate"] = ImpersonateTarget.from_str(
            settings.youtube_impersonate,
        )
    if settings.youtube_proxy_url:
        proxy = settings.youtube_proxy_url.get_secret_value().strip()
        if proxy:
            options["proxy"] = proxy
    if options:
        options["logger"] = _ProviderLogger(options.get("proxy"))
    return options


@contextmanager
def youtube_dl(
    options: dict[str, Any], cookie_file: Path | None = None,
) -> Iterator[YoutubeDL]:
    """Evita modificar el secreto original y compartir escrituras entre trabajos."""
    # Evitar que credenciales del proxy aparezcan en tracebacks de API y worker.
    try:
        with _youtube_dl(options, cookie_file) as ydl:
            yield ydl
    except subprocess.TimeoutExpired:
        logger.warning("youtube_provider_timeout")
        raise DownloadError(
            "El proveedor de YouTube agotó el tiempo de espera.",
        ) from None
    except DownloadError as error:
        safe_message = _redact(str(error), options.get("proxy"))
        if safe_message != str(error):
            raise DownloadError(safe_message) from None
        raise


@contextmanager
def _youtube_dl(
    options: dict[str, Any], cookie_file: Path | None,
) -> Iterator[YoutubeDL]:
    if cookie_file is None:
        logger.info(
            "youtube_cookie_file_not_configured: "
            "VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE no está configurada; "
            "se continúa sin cookies."
        )
        with YoutubeDL(options) as ydl:
            yield ydl
        return

    # yt-dlp guarda cookies al cerrar: los secretos de Render son de solo lectura.
    with TemporaryDirectory(prefix="video-transcriber-cookies-") as directory:
        writable_cookies = Path(directory) / "cookies.txt"
        try:
            copyfile(cookie_file, writable_cookies)
        except FileNotFoundError:
            logger.warning(
                "youtube_cookie_file_missing: %s; se continúa sin cookies. "
                "Revisa VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE y el archivo secreto.",
                cookie_file,
            )
            effective_options = options
        except OSError as error:
            logger.error(
                "youtube_cookie_file_unreadable: %s; "
                "no se pudo copiar el archivo de cookies (%s, errno=%s).",
                cookie_file,
                type(error).__name__,
                error.errno,
            )
            raise
        else:
            logger.info(
                "youtube_cookie_file_loaded: %s; "
                "se usa una copia temporal para esta operación de yt-dlp.",
                cookie_file,
            )
            effective_options = {**options, "cookiefile": str(writable_cookies)}
        with YoutubeDL(effective_options) as ydl:
            yield ydl
