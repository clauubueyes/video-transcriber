"""Comprueba metadatos y audio con la configuración real del servidor."""

import argparse
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import AnyHttpUrl

from app.core.config import Settings
from app.services.audio import YtDlpAudioFetcher
from app.services.duration import YtDlpVideoDurationProbe
from app.services.source_validation import validate_allowed_source
from app.services.ytdlp import youtube_download_options


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Enlace público de YouTube que quieres comprobar")
    parser.add_argument(
        "--audio", action="store_true", help="Descargar también el audio",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings()
    options = youtube_download_options(settings)
    try:
        validate_allowed_source(AnyHttpUrl(args.url), settings.allowed_domain_set)
        duration = YtDlpVideoDurationProbe(
            cookie_file=settings.youtube_cookie_file, download_options=options,
        ).get_duration_seconds(args.url)
        result = {"status": "ok", "duration_seconds": duration}
        if args.audio:
            with TemporaryDirectory(prefix="youtube-check-") as directory:
                audio = YtDlpAudioFetcher(
                    cookie_file=settings.youtube_cookie_file, download_options=options,
                ).fetch(args.url, Path(directory))
                result["audio_bytes"] = audio.stat().st_size
        print(json.dumps(result))
    except Exception:
        # El detalle del extractor ya lo registra youtube_dl; no duplicar
        # posibles secretos de otras excepciones en la salida JSON.
        print(json.dumps({
            "status": "failed", "error": "Consulta los logs anteriores.",
        }))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
