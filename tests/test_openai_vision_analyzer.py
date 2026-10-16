import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.vision.openai_analyzer import (
    MAX_IMAGE_BYTES,
    OpenAIImageAnalyzer,
    VisionAnalysisError,
    _image_data_url,
)
from app.vision.schemas import CleanlinessVisionResult, ImageQuality


class FakeResponses:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.output = output
        self.arguments: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> object:
        self.arguments = kwargs
        return SimpleNamespace(
            id="resp_test_cleanliness",
            output_parsed=self.output,
            usage=SimpleNamespace(input_tokens=123, output_tokens=45),
        )


class FakeOpenAI:
    def __init__(self, output: dict[str, object] | None) -> None:
        self.responses = FakeResponses(output)


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


def test_analyzer_sends_data_url_and_returns_typed_result(tmp_path: Path) -> None:
    image_path = tmp_path / "room.jpg"
    save_image(image_path)
    client = FakeOpenAI(cleanliness_payload())
    analyzer = OpenAIImageAnalyzer(
        api_key="test-key",
        model="gpt-test-vision",
        client=client,  # type: ignore[arg-type]
    )

    analysis = analyzer.analyze(image_path, detail="high")

    assert isinstance(analysis.result, CleanlinessVisionResult)
    assert analysis.result.image_quality is ImageQuality.USABLE
    assert analysis.result.overall_score == 42
    assert analysis.metadata.model == "gpt-test-vision"
    assert analysis.metadata.response_id == "resp_test_cleanliness"
    assert analysis.metadata.input_tokens == 123
    assert analysis.metadata.output_tokens == 45

    assert client.responses.arguments is not None
    request_input = client.responses.arguments["input"]
    assert isinstance(request_input, list)
    image_content = request_input[0]["content"][1]  # type: ignore[index]
    assert image_content["detail"] == "high"  # type: ignore[index]
    assert str(image_content["image_url"]).startswith("data:image/jpeg;base64,")  # type: ignore[index]


def test_analyzer_rejects_missing_structured_output(tmp_path: Path) -> None:
    image_path = tmp_path / "room.png"
    save_image(image_path, image_format="PNG")
    analyzer = OpenAIImageAnalyzer(
        api_key="test-key",
        client=FakeOpenAI(None),  # type: ignore[arg-type]
    )

    with pytest.raises(VisionAnalysisError, match="no structured"):
        analyzer.analyze(image_path)


def test_image_data_url_uses_detected_format_not_extension(tmp_path: Path) -> None:
    image_path = tmp_path / "misleading.jpg"
    save_image(image_path, image_format="PNG")

    data_url = _image_data_url(image_path)
    prefix, encoded = data_url.split(",", maxsplit=1)

    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == image_path.read_bytes()


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
        _image_data_url(image_path)


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
        _image_data_url(image_path)
