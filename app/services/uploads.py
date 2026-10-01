"""Almacenamiento temporal y validación básica de archivos subidos."""

from io import BufferedIOBase
from pathlib import Path
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
