from io import BytesIO

import pytest

from app.services.uploads import TemporaryUploadStore, UploadValidationError


def test_store_saves_supported_upload_with_safe_name(tmp_path) -> None:
    store = TemporaryUploadStore(tmp_path, max_upload_bytes=10)

    stored = store.save(BytesIO(b"audio"), "../../grabacion.MP3")

    assert stored.parent == tmp_path
    assert stored.suffix == ".mp3"
    assert stored.read_bytes() == b"audio"


def test_store_rejects_unsupported_upload_format(tmp_path) -> None:
    store = TemporaryUploadStore(tmp_path, max_upload_bytes=10)

    with pytest.raises(UploadValidationError, match="formato"):
        store.save(BytesIO(b"text"), "notas.txt")


def test_store_removes_partial_file_when_upload_exceeds_limit(tmp_path) -> None:
    store = TemporaryUploadStore(tmp_path, max_upload_bytes=3)

    with pytest.raises(UploadValidationError, match="tamaño máximo"):
        store.save(BytesIO(b"audio"), "grabacion.wav")

    assert list(tmp_path.iterdir()) == []
