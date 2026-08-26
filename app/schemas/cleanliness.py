from typing import Annotated

from pydantic import BaseModel, Field

from app.domain.cleanliness import AnalysisClassification
from app.schemas.mode import ModeResponse


class AreaAssessment(BaseModel):
    area: str = Field(min_length=1, max_length=100, examples=["floor"])
    cleanliness_score: int = Field(ge=0, le=100)
    status: AnalysisClassification
    issues: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list,
        max_length=20,
    )


class CleanlinessAnalysisResult(BaseModel):
    classification: AnalysisClassification
    confidence: float = Field(ge=0, le=1)
    overall_score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=500)
    areas: list[AreaAssessment] = Field(min_length=1, max_length=30)


class TransitionSummary(BaseModel):
    previous_state: str
    current_state: str
    trigger: str
    timer_action: str


class ModeTransitionResponse(BaseModel):
    mode: ModeResponse
    transition: TransitionSummary | None
    replayed: bool = False
