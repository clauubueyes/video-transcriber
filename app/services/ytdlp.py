"""Contexto yt-dlp con una copia temporal de las cookies del servidor."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any

from yt_dlp import YoutubeDL

logger = logging.getLogger("video_transcriber.ytdlp")


@contextmanager
def youtube_dl(
    options: dict[str, Any], cookie_file: Path | None = None,
) -> Iterator[YoutubeDL]:
    """Evita modificar el secreto original y compartir escrituras entre trabajos."""
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
