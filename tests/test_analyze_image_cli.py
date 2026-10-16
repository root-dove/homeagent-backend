import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import analyze_image
from app.vision.openai_analyzer import OpenAIAnalysis, OpenAIAnalysisMetadata
from app.vision.schemas import CleanlinessVisionResult


def result() -> CleanlinessVisionResult:
    return CleanlinessVisionResult.model_validate(
        {
            "image_quality": "usable",
            "quality_issues": [],
            "classification": "clean",
            "confidence": 0.88,
            "overall_score": 91,
            "summary": "정돈된 방입니다.",
            "areas": [
                {
                    "area": "floor",
                    "cleanliness_score": 94,
                    "status": "clean",
                    "issues": [],
                    "evidence": ["바닥 통로에 물건이 없습니다."],
                }
            ],
        }
    )


def test_cli_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        analyze_image,
        "build_parser",
        lambda: SimpleNamespace(parse_args=lambda: SimpleNamespace()),
    )

    with pytest.raises(SystemExit) as captured:
        analyze_image.main()

    assert captured.value.code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_cli_prints_json_without_exposing_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_path = tmp_path / "room.jpg"
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setattr(
        analyze_image,
        "build_parser",
        lambda: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                image=image_path,
                model="gpt-test-vision",
                detail="high",
            )
        ),
    )

    class FakeAnalyzer:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs == {"api_key": "secret-key", "model": "gpt-test-vision"}

        def analyze(self, supplied_path: Path, **kwargs: object) -> OpenAIAnalysis:
            assert supplied_path == image_path
            assert kwargs == {"detail": "high"}
            return OpenAIAnalysis(
                result=result(),
                metadata=OpenAIAnalysisMetadata(
                    model="gpt-test-vision",
                    response_id="resp_test",
                    input_tokens=100,
                    output_tokens=50,
                ),
            )

    monkeypatch.setattr(analyze_image, "OpenAIImageAnalyzer", FakeAnalyzer)

    analyze_image.main()

    output = json.loads(capsys.readouterr().out)
    assert output["result"]["overall_score"] == 91
    assert output["metadata"]["response_id"] == "resp_test"
    assert "secret-key" not in json.dumps(output)
