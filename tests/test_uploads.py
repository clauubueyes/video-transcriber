from io import BytesIO
from os import utime
from time import time

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


def test_store_removes_only_old_unreferenced_uploads(tmp_path) -> None:
    store = TemporaryUploadStore(tmp_path, max_upload_bytes=10)
    referenced = store.save(BytesIO(b"audio"), "referenced.webm")
    orphaned = store.save(BytesIO(b"audio"), "orphaned.webm")
    recent = store.save(BytesIO(b"audio"), "recent.webm")
    old_timestamp = time() - 61
    utime(referenced, (old_timestamp, old_timestamp))
    utime(orphaned, (old_timestamp, old_timestamp))

    removed = store.remove_orphaned({str(referenced)}, older_than_seconds=60)

    assert removed == 1
    assert referenced.exists()
    assert not orphaned.exists()
    assert recent.exists()
