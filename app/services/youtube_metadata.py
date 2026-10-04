"""Reutilización breve y acotada de metadatos dentro de un proceso."""

import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Any, Protocol

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError, ReExtractInfo

logger = logging.getLogger("video_transcriber.youtube_metadata")


class MetadataProvider(Protocol):
    def extract_info(self, url: str, download: bool) -> dict[str, Any]: ...

    def process_ie_result(
        self, info: dict[str, Any], download: bool,
    ) -> dict[str, Any]: ...


class YoutubeMetadataCache:
    """Hasta 4 MB de JSON y 16 vídeos; cada lectura obtiene una copia propia."""

    def __init__(
        self, *, ttl_seconds: float = 300, max_bytes: int = 4_000_000,
        max_entries: int = 16, clock: Callable[[], float] = monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._size_bytes = 0
        self._lock = Lock()
        self._load_lock = Lock()

    def get(self, source_url: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_expired()
            entry = self._entries.get(source_url)
            if entry is None:
                return None
            self._entries.move_to_end(source_url)
            payload = entry[1]
        return json.loads(payload)

    def put(self, source_url: str, metadata: dict[str, Any]) -> None:
        if (
            not metadata.get("id") or not metadata.get("formats")
            or metadata.get("_type", "video") != "video"
            or metadata.get("is_live")
        ):
            return
        compact = {
            key: value for key, value in metadata.items()
            if key not in {"comments", "description", "thumbnails",
                           "heatmap", "tags", "categories"}
        }
        try:
            payload = json.dumps(
                YoutubeDL.sanitize_info(compact, remove_private_keys=True),
                ensure_ascii=True, allow_nan=False, separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return
        size = len(payload) + len(source_url.encode("utf-8"))
        if size > self._max_bytes:
            return
        with self._lock:
            self._purge_expired()
            self._discard(source_url)
            while self._entries and (
                self._size_bytes + size > self._max_bytes
                or len(self._entries) >= self._max_entries
            ):
                self._discard(next(iter(self._entries)))
            self._entries[source_url] = (self._clock() + self._ttl_seconds, payload)
            self._size_bytes += size

    def get_or_load(
        self, source_url: str, loader: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        # Una extracción a la vez; agrupa peticiones simultáneas al mismo vídeo.
        with self._load_lock:
            metadata = self.get(source_url)
            if metadata is not None:
                return metadata
            metadata = loader()
            self.put(source_url, metadata)
            return metadata

    def discard(self, source_url: str) -> None:
        with self._lock:
            self._discard(source_url)

    def _discard(self, source_url: str) -> None:
        entry = self._entries.pop(source_url, None)
        if entry is not None:
            self._size_bytes -= len(entry[1]) + len(source_url.encode("utf-8"))

    def _purge_expired(self) -> None:
        now = self._clock()
        for source_url, (expires_at, _) in list(self._entries.items()):
            if expires_at <= now:
                self._discard(source_url)


def extract_with_metadata(
    provider: MetadataProvider, source_url: str, *, download: bool,
    cache: YoutubeMetadataCache | None,
) -> dict[str, Any]:
    """Evita repetir la extracción y refresca una vez si falla una URL temporal."""
    if cache is None:
        return provider.extract_info(source_url, download=download)
    metadata = cache.get(source_url)
    if metadata is not None:
        logger.info("youtube_metadata_cache_hit")
        if not download:
            return metadata
        try:
            return provider.process_ie_result(metadata, download=True)
        except (DownloadError, ExtractorError, ReExtractInfo) as error:
            cache.discard(source_url)
            if "429" in str(error) or "too many requests" in str(error).lower():
                if isinstance(error, DownloadError):
                    raise
                raise DownloadError(str(error)) from error
            logger.info("youtube_metadata_cache_refresh")
    metadata = cache.get_or_load(
        source_url, lambda: provider.extract_info(source_url, download=False),
    )
    if not download:
        return metadata
    try:
        return provider.process_ie_result(metadata, download=True)
    except (ExtractorError, ReExtractInfo) as error:
        raise DownloadError(str(error)) from error
