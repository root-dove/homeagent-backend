import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import errors, types
from PIL import Image, UnidentifiedImageError

from app.vision.prompt import CLEANLINESS_ANALYSIS_INSTRUCTIONS, CLEANLINESS_ANALYSIS_REQUEST
from app.vision.schemas import CleanlinessVisionResult

MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MediaResolution = Literal["low", "medium", "high"]
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
        model: str = "gemini-2.5-flash",
        timeout_seconds: float = 60,
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
        *,
        media_resolution: MediaResolution = "high",
    ) -> GeminiAnalysis:
        image_bytes, media_type = _image_bytes_and_media_type(image_path)
        resolution = {
            "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
            "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
        }[media_resolution]
        contents = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                types.Part.from_text(text=CLEANLINESS_ANALYSIS_REQUEST),
            ],
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=CLEANLINESS_ANALYSIS_INSTRUCTIONS,
                    response_mime_type="application/json",
                    response_json_schema=CleanlinessVisionResult.model_json_schema(),
                    media_resolution=resolution,
                    temperature=0.1,
                ),
            )
        except errors.APIError as error:
            raise VisionAnalysisError(_safe_api_error(error)) from error

        if response.parsed is None:
            raise VisionAnalysisError("Gemini returned no structured cleanliness result.")
        result = CleanlinessVisionResult.model_validate(response.parsed)
        usage = response.usage_metadata
        return GeminiAnalysis(
            result=result,
            metadata=GeminiAnalysisMetadata(
                model=self._model,
                model_version=response.model_version,
                response_id=response.response_id,
                input_tokens=usage.prompt_token_count if usage is not None else None,
                output_tokens=usage.candidates_token_count if usage is not None else None,
                total_tokens=usage.total_token_count if usage is not None else None,
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
