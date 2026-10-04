from app.core.config import Settings
from app.services.processor_factory import create_local_processor, create_processors
from app.services.subtitle_processor import SubtitleFirstProcessor


def test_factory_builds_subtitle_first_local_processor(tmp_path) -> None:
    model_path = tmp_path / "whisper-small"
    model_path.mkdir()

    processor = create_local_processor(
        model_path,
        device="cpu",
        compute_type="int8",
    )

    assert isinstance(processor, SubtitleFirstProcessor)


def test_local_url_and_file_processors_share_one_model(tmp_path):
    settings = Settings(token="test-token", model_path=tmp_path,
                        groq_api_key=None, _env_file=None)
    url_processor, file_processor = create_processors(settings)
    assert url_processor._audio_fallback._transcriber is file_processor._transcriber


def test_groq_url_and_file_processors_share_chunk_configuration():
    settings = Settings(token="test-token", groq_api_key="test-key",
                        groq_chunk_seconds=60, _env_file=None)
    url_processor, file_processor = create_processors(settings)
    transcriber = file_processor._transcriber
    assert url_processor._audio_fallback._transcriber is transcriber
    assert transcriber._chunk_seconds == 60
