import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from google import genai
from google.genai import errors, interactions, types
from PIL import Image, UnidentifiedImageError

from app.vision.prompt import CLEANLINESS_ANALYSIS_INSTRUCTIONS, CLEANLINESS_ANALYSIS_REQUEST
from app.vision.schemas import CleanlinessVisionResult

MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
GEMINI_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]+")


class VisionAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeminiAnalysisMetadata:
    model: str
    model_version: str | None
    response_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class GeminiAnalysis:
    result: CleanlinessVisionResult
    metadata: GeminiAnalysisMetadata


class GeminiImageAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-3.8-flash",
        timeout_seconds: float = 180,
        max_retries: int = 2,
        client: genai.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key must not be empty.")
        if not model:
            raise ValueError("Gemini model must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Max retries must not be negative.")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=round(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=max_retries + 1),
            ),
        )

    def analyze(
        self,
        image_path: Path,
    ) -> GeminiAnalysis:
        image_bytes, media_type = _image_bytes_and_media_type(image_path)
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        prompt = f"{CLEANLINESS_ANALYSIS_INSTRUCTIONS}\n\n{CLEANLINESS_ANALYSIS_REQUEST}"
        try:
            response = cast(
                interactions.Interaction,
                self._client.interactions.create(
                    model=self._model,
                    input=[
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "data": encoded_image,
                            "mime_type": media_type,
                        },
                    ],
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": _gemini_response_schema(),
                    },
                    timeout=self._timeout_seconds,
                ),
            )
        except Exception as error:
            if isinstance(error, errors.APIError):
                raise VisionAnalysisError(_safe_api_error(error)) from error
            if type(error).__name__ == "APITimeoutError":
                raise VisionAnalysisError(
                    f"Gemini vision request timed out after {self._timeout_seconds:g} seconds."
                ) from error
            if type(error).__module__.startswith("google.genai._gaos"):
                safe_message = GEMINI_KEY_PATTERN.sub("[REDACTED]", str(error))[:1000]
                raise VisionAnalysisError(
                    f"Gemini vision request failed: {safe_message}"
                ) from error
            raise

        if not response.output_text:
            raise VisionAnalysisError("Gemini returned no structured cleanliness result.")
        result = CleanlinessVisionResult.model_validate_json(response.output_text)
        usage = response.usage
        return GeminiAnalysis(
            result=result,
            metadata=GeminiAnalysisMetadata(
                model=self._model,
                model_version=str(response.model) if response.model is not None else None,
                response_id=response.id,
                input_tokens=usage.total_input_tokens if usage is not None else None,
                output_tokens=usage.total_output_tokens if usage is not None else None,
                total_tokens=usage.total_tokens if usage is not None else None,
            ),
        )


def _image_bytes_and_media_type(image_path: Path) -> tuple[bytes, str]:
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
        image_bytes = image_path.read_bytes()
    except OSError as error:
        raise VisionAnalysisError(f"Image file '{image_path}' cannot be read.") from error
    return image_bytes, media_type


def _safe_api_error(error: errors.APIError) -> str:
    code = getattr(error, "code", "unknown")
    status = getattr(error, "status", "UNKNOWN") or "UNKNOWN"
    message = getattr(error, "message", "Request was rejected.") or "Request was rejected."
    safe_message = GEMINI_KEY_PATTERN.sub("[REDACTED]", str(message))
    return f"Gemini vision request failed: HTTP {code} {status}: {safe_message}"


def _gemini_response_schema() -> dict[str, object]:
    classification = ["clean", "uncertain", "dirty"]
    area_schema = {
        "type": "object",
        "properties": {
            "area": {"type": "string"},
            "cleanliness_score": {"type": "integer"},
            "status": {"type": "string", "enum": classification},
            "issues": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["area", "cleanliness_score", "status", "issues", "evidence"],
    }
    return {
        "type": "object",
        "properties": {
            "image_quality": {
                "type": "string",
                "enum": ["usable", "too_dark", "blurry", "obstructed", "insufficient_view"],
            },
            "quality_issues": {"type": "array", "items": {"type": "string"}},
            "classification": {"type": "string", "enum": classification},
            "confidence": {"type": "number"},
            "overall_score": {"type": "integer"},
            "summary": {"type": "string"},
            "areas": {"type": "array", "items": area_schema},
        },
        "required": [
            "image_quality",
            "quality_issues",
            "classification",
            "confidence",
            "overall_score",
            "summary",
            "areas",
        ],
    }
