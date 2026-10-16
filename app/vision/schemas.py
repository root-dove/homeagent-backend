from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.domain.cleanliness import AnalysisClassification


class ImageQuality(StrEnum):
    USABLE = "usable"
    TOO_DARK = "too_dark"
    BLURRY = "blurry"
    OBSTRUCTED = "obstructed"
    INSUFFICIENT_VIEW = "insufficient_view"


class VisionAreaAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: str = Field(min_length=1, max_length=100)
    cleanliness_score: int = Field(ge=0, le=100)
    status: AnalysisClassification
    issues: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=0,
        max_length=20,
    )
    evidence: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=1,
        max_length=20,
    )


class CleanlinessVisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_quality: ImageQuality
    quality_issues: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=0,
        max_length=20,
    )
    classification: AnalysisClassification
    confidence: float = Field(ge=0, le=1)
    overall_score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=500)
    areas: list[VisionAreaAssessment] = Field(min_length=1, max_length=30)
