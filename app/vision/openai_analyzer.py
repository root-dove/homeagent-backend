import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openai import OpenAI, OpenAIError
from PIL import Image, UnidentifiedImageError

from app.vision.prompt import CLEANLINESS_ANALYSIS_INSTRUCTIONS, CLEANLINESS_ANALYSIS_REQUEST
from app.vision.schemas import CleanlinessVisionResult

MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class VisionAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OpenAIAnalysisMetadata:
    model: str
    response_id: str
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class OpenAIAnalysis:
    result: CleanlinessVisionResult
    metadata: OpenAIAnalysisMetadata


class OpenAIImageAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-5.5",
        timeout_seconds: float = 60,
        max_retries: int = 2,
        client: OpenAI | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key must not be empty.")
        if not model:
            raise ValueError("OpenAI model must not be empty.")
        self._model = model
        self._client = client or OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def analyze(
        self,
        image_path: Path,
        *,
        detail: Literal["auto", "low", "high", "original"] = "high",
    ) -> OpenAIAnalysis:
        image_data_url = _image_data_url(image_path)
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=CLEANLINESS_ANALYSIS_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": CLEANLINESS_ANALYSIS_REQUEST},
                            {
                                "type": "input_image",
                                "image_url": image_data_url,
                                "detail": detail,
                            },
                        ],
                    }
                ],
                text_format=CleanlinessVisionResult,
            )
        except OpenAIError as error:
            raise VisionAnalysisError(
                f"OpenAI vision request failed ({type(error).__name__})."
            ) from error

        if response.output_parsed is None:
            raise VisionAnalysisError("OpenAI returned no structured cleanliness result.")
        result = CleanlinessVisionResult.model_validate(response.output_parsed)
        usage = response.usage
        return OpenAIAnalysis(
            result=result,
            metadata=OpenAIAnalysisMetadata(
                model=self._model,
                response_id=response.id,
                input_tokens=usage.input_tokens if usage is not None else None,
                output_tokens=usage.output_tokens if usage is not None else None,
            ),
        )


def _image_data_url(image_path: Path) -> str:
    try:
        size_bytes = image_path.stat().st_size
    except OSError as error:
        raise VisionAnalysisError(f"Image file '{image_path}' cannot be read.") from error
    if size_bytes == 0:
        raise VisionAnalysisError("Image file is empty.")
    if size_bytes > MAX_IMAGE_BYTES:
        raise VisionAnalysisError(f"Image exceeds the {MAX_IMAGE_BYTES} byte test limit.")

    try:
        with Image.open(image_path) as image:
            media_type = SUPPORTED_FORMATS.get(image.format or "")
            if media_type is None:
                raise VisionAnalysisError("Only JPEG, PNG, and WebP images are supported.")
            image.verify()
    except VisionAnalysisError:
        raise
    except (OSError, UnidentifiedImageError) as error:
        raise VisionAnalysisError("Image is not a valid supported image.") from error

    try:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError as error:
        raise VisionAnalysisError(f"Image file '{image_path}' cannot be read.") from error
    return f"data:{media_type};base64,{encoded}"
