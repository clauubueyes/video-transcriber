"""Almacenamiento temporal y validación básica de archivos subidos."""

from io import BufferedIOBase
from pathlib import Path
from time import time
from uuid import uuid4

_ALLOWED_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm"}
)
_CHUNK_SIZE = 1024 * 1024


class UploadValidationError(ValueError):
    """El archivo no cumple las restricciones de la API."""


class TemporaryUploadStore:
    """Guarda subidas con nombre seguro y límite de tamaño estricto."""

    def __init__(self, directory: Path, max_upload_bytes: int) -> None:
        self._directory = directory
        self._max_upload_bytes = max_upload_bytes

    def save(self, source: BufferedIOBase, filename: str) -> Path:
        """Copia una subida por bloques y borra restos en caso de error."""
        extension = Path(filename).suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise UploadValidationError("El formato de archivo no es compatible.")

        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / f"upload-{uuid4().hex}{extension}"
        total_bytes = 0
        try:
            with target.open("xb") as destination:
                while chunk := source.read(_CHUNK_SIZE):
                    total_bytes += len(chunk)
                    if total_bytes > self._max_upload_bytes:
                        raise UploadValidationError(
                            "El archivo supera el tamaño máximo permitido."
                        )
                    destination.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

    def remove_orphaned(
        self,
        referenced_paths: set[str],
        older_than_seconds: int,
    ) -> int:
        """Borra subidas propias antiguas que ya no están en la cola SQLite."""
        if not self._directory.exists():
            return 0

        directory = self._directory.resolve()
        referenced = {
            path.resolve()
            for value in referenced_paths
            if (path := Path(value)).resolve().is_relative_to(directory)
        }
        oldest_allowed_mtime = time() - older_than_seconds
        removed = 0
        for candidate in directory.glob("upload-*"):
            if (
                not candidate.is_file()
                or candidate.resolve() in referenced
                or candidate.stat().st_mtime > oldest_allowed_mtime
            ):
                continue
            try:
                candidate.unlink()
            except OSError:
                continue
            removed += 1
        return removed
