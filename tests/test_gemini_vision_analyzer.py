import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors
from PIL import Image

from app.vision.gemini_analyzer import (
    MAX_IMAGE_BYTES,
    GeminiImageAnalyzer,
    VisionAnalysisError,
    _gemini_response_schema,
    _image_bytes_and_media_type,
)
from app.vision.schemas import CleanlinessVisionResult, ImageQuality


class FakeInteractions:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.output = output
        self.arguments: dict[str, object] | None = None

    def create(self, **kwargs: object) -> object:
        self.arguments = kwargs
        return SimpleNamespace(
            id="interaction_test_cleanliness",
            model="gemini-test-vision-001",
            output_text=json.dumps(self.output) if self.output is not None else None,
            usage=SimpleNamespace(
                total_input_tokens=123,
                total_output_tokens=45,
                total_tokens=168,
            ),
        )


class FakeGemini:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.interactions = FakeInteractions(output)


class RejectingInteractions:
    def create(self, **kwargs: object) -> object:
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
        self.interactions = RejectingInteractions()


class APITimeoutError(Exception):
    pass


class TimingOutInteractions:
    def create(self, **kwargs: object) -> object:
        raise APITimeoutError("Request timed out with internal request details")


class TimingOutGemini:
    def __init__(self) -> None:
        self.interactions = TimingOutInteractions()


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

    analysis = analyzer.analyze(image_path)

    assert isinstance(analysis.result, CleanlinessVisionResult)
    assert analysis.result.image_quality is ImageQuality.USABLE
    assert analysis.result.overall_score == 42
    assert analysis.metadata.model == "gemini-test-vision"
    assert analysis.metadata.model_version == "gemini-test-vision-001"
    assert analysis.metadata.response_id == "interaction_test_cleanliness"
    assert analysis.metadata.input_tokens == 123
    assert analysis.metadata.output_tokens == 45
    assert analysis.metadata.total_tokens == 168

    assert client.interactions.arguments is not None
    request_input = client.interactions.arguments["input"]
    assert isinstance(request_input, list)
    assert request_input[0]["type"] == "text"  # type: ignore[index]
    image_input = request_input[1]
    assert image_input["type"] == "image"  # type: ignore[index]
    assert image_input["mime_type"] == "image/jpeg"  # type: ignore[index]
    assert "resolution" not in image_input  # type: ignore[operator]
    assert base64.b64decode(image_input["data"]) == image_path.read_bytes()  # type: ignore[index]

    response_format = client.interactions.arguments["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "text"
    assert response_format["mime_type"] == "application/json"
    schema = response_format["schema"]
    assert schema == _gemini_response_schema()
    assert "additionalProperties" not in schema
    assert client.interactions.arguments["timeout"] == 180


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


def test_analyzer_reports_timeout_without_traceback_details(tmp_path: Path) -> None:
    image_path = tmp_path / "room.jpg"
    save_image(image_path)
    analyzer = GeminiImageAnalyzer(
        api_key="test-key",
        timeout_seconds=240,
        client=TimingOutGemini(),  # type: ignore[arg-type]
    )

    with pytest.raises(VisionAnalysisError) as captured:
        analyzer.analyze(image_path)

    assert str(captured.value) == "Gemini vision request timed out after 240 seconds."


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
