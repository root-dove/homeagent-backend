from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors, types
from PIL import Image

from app.vision.gemini_analyzer import (
    MAX_IMAGE_BYTES,
    GeminiImageAnalyzer,
    VisionAnalysisError,
    _image_bytes_and_media_type,
)
from app.vision.schemas import CleanlinessVisionResult, ImageQuality


class FakeModels:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.output = output
        self.arguments: dict[str, object] | None = None

    def generate_content(self, **kwargs: object) -> object:
        self.arguments = kwargs
        return SimpleNamespace(
            response_id="response_test_cleanliness",
            model_version="gemini-test-vision-001",
            parsed=self.output,
            usage_metadata=SimpleNamespace(
                prompt_token_count=123,
                candidates_token_count=45,
                total_token_count=168,
            ),
        )


class FakeGemini:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.models = FakeModels(output)


class RejectingModels:
    def generate_content(self, **kwargs: object) -> object:
        raise errors.ClientError(
            404,
            {
                "error": {
                    "message": "models/gemini-missing is not found for key AIzaTESTSECRET",
                    "status": "NOT_FOUND",
                }
            },
        )


class RejectingGemini:
    def __init__(self) -> None:
        self.models = RejectingModels()


def cleanliness_payload() -> dict[str, object]:
    return {
        "image_quality": "usable",
        "quality_issues": [],
        "classification": "dirty",
        "confidence": 0.91,
        "overall_score": 42,
        "summary": "바닥과 책상에 정리가 필요한 물건이 보입니다.",
        "areas": [
            {
                "area": "floor",
                "cleanliness_score": 35,
                "status": "dirty",
                "issues": ["바닥의 옷을 정리하세요."],
                "evidence": ["바닥 통로에 여러 옷이 놓여 있습니다."],
            }
        ],
    }


def save_image(path: Path, *, image_format: str = "JPEG") -> None:
    Image.new("RGB", (1280, 720), color=(120, 100, 80)).save(path, format=image_format)


def test_analyzer_sends_image_bytes_and_returns_typed_result(tmp_path: Path) -> None:
    image_path = tmp_path / "room.jpg"
    save_image(image_path)
    client = FakeGemini(cleanliness_payload())
    analyzer = GeminiImageAnalyzer(
        api_key="test-key",
        model="gemini-test-vision",
        client=client,  # type: ignore[arg-type]
    )

    analysis = analyzer.analyze(image_path, media_resolution="high")

    assert isinstance(analysis.result, CleanlinessVisionResult)
    assert analysis.result.image_quality is ImageQuality.USABLE
    assert analysis.result.overall_score == 42
    assert analysis.metadata.model == "gemini-test-vision"
    assert analysis.metadata.model_version == "gemini-test-vision-001"
    assert analysis.metadata.response_id == "response_test_cleanliness"
    assert analysis.metadata.input_tokens == 123
    assert analysis.metadata.output_tokens == 45
    assert analysis.metadata.total_tokens == 168

    assert client.models.arguments is not None
    contents = client.models.arguments["contents"]
    assert isinstance(contents, types.Content)
    assert contents.parts is not None
    image_part = contents.parts[0]
    assert isinstance(image_part, types.Part)
    assert image_part.inline_data is not None
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert image_part.inline_data.data == image_path.read_bytes()

    config = client.models.arguments["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.response_schema is CleanlinessVisionResult
    assert config.media_resolution is types.MediaResolution.MEDIA_RESOLUTION_HIGH


def test_analyzer_rejects_missing_structured_output(tmp_path: Path) -> None:
    image_path = tmp_path / "room.png"
    save_image(image_path, image_format="PNG")
    analyzer = GeminiImageAnalyzer(
        api_key="test-key",
        client=FakeGemini(None),  # type: ignore[arg-type]
    )

    with pytest.raises(VisionAnalysisError, match="no structured"):
        analyzer.analyze(image_path)


def test_analyzer_reports_safe_api_error_without_exposing_key(tmp_path: Path) -> None:
    image_path = tmp_path / "room.jpg"
    save_image(image_path)
    analyzer = GeminiImageAnalyzer(
        api_key="test-key",
        client=RejectingGemini(),  # type: ignore[arg-type]
    )

    with pytest.raises(VisionAnalysisError) as captured:
        analyzer.analyze(image_path)

    message = str(captured.value)
    assert "HTTP 404 NOT_FOUND" in message
    assert "gemini-missing" in message
    assert "AIzaTESTSECRET" not in message
    assert "[REDACTED]" in message


def test_image_bytes_use_detected_format_not_extension(tmp_path: Path) -> None:
    image_path = tmp_path / "misleading.jpg"
    save_image(image_path, image_format="PNG")

    image_bytes, media_type = _image_bytes_and_media_type(image_path)

    assert media_type == "image/png"
    assert image_bytes == image_path.read_bytes()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("empty.jpg", b"", "empty"),
        ("invalid.jpg", b"not-an-image", "valid supported image"),
    ],
)
def test_image_validation_rejects_invalid_files(
    tmp_path: Path,
    name: str,
    content: bytes,
    message: str,
) -> None:
    image_path = tmp_path / name
    image_path.write_bytes(content)

    with pytest.raises(VisionAnalysisError, match=message):
        _image_bytes_and_media_type(image_path)


def test_image_validation_rejects_oversized_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "room.jpg"
    save_image(image_path)

    monkeypatch.setattr(
        Path,
        "stat",
        lambda self: SimpleNamespace(st_size=MAX_IMAGE_BYTES + 1),
    )
    with pytest.raises(VisionAnalysisError, match="exceeds"):
        _image_bytes_and_media_type(image_path)
