"""Contexto yt-dlp con una copia temporal de las cookies del servidor."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any

from yt_dlp import YoutubeDL


@contextmanager
def youtube_dl(
    options: dict[str, Any], cookie_file: Path | None = None,
) -> Iterator[YoutubeDL]:
    """Evita modificar el secreto original y compartir escrituras entre trabajos."""
    if cookie_file is None:
        with YoutubeDL(options) as ydl:
            yield ydl
        return

    # yt-dlp guarda cookies al cerrar: los secretos de Render son de solo lectura.
    with TemporaryDirectory(prefix="video-transcriber-cookies-") as directory:
        writable_cookies = Path(directory) / "cookies.txt"
        copyfile(cookie_file, writable_cookies)
        with YoutubeDL({**options, "cookiefile": str(writable_cookies)}) as ydl:
            yield ydl
