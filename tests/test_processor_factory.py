from app.services.processor_factory import create_local_processor
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
