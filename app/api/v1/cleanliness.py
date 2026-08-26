from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.domain.cleanliness import CleanlinessState, InvalidStateTransition, TransitionResult
from app.models import Mode
from app.schemas import (
    CleanlinessAnalysisResult,
    ModeResponse,
    ModeTransitionResponse,
    TransitionSummary,
)
from app.services.cleanliness_flow import (
    AnalysisResultNotExpected,
    InvalidModeConfiguration,
    ModeDisabled,
    apply_analysis_result,
    request_cleaning_verification,
    start_analysis,
)
from app.services.cleanliness_state import (
    InvalidPersistedState,
    read_cleanliness_state,
)
from app.services.cleanliness_state import (
    UnsupportedModeType as UnsupportedCleanlinessModeType,
)
from app.services.modes import ModeNotFound, require_mode

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.post("/{instance_key}/analysis/start", response_model=ModeTransitionResponse)
def begin_analysis(
    instance_key: str,
    session: DatabaseSession,
    response: Response,
) -> ModeTransitionResponse:
    mode = _require_mode(session, instance_key)
    try:
        if mode.enabled and read_cleanliness_state(mode) is CleanlinessState.ANALYZING:
            return _replayed_transition(mode, response)
        result = start_analysis(mode)
    except _FLOW_ERRORS as error:
        _raise_flow_conflict(error)

    return _commit_transition(session, mode, result)


@router.post("/{instance_key}/analysis/result", response_model=ModeTransitionResponse)
def submit_analysis_result(
    instance_key: str,
    payload: CleanlinessAnalysisResult,
    session: DatabaseSession,
) -> ModeTransitionResponse:
    mode = _require_mode(session, instance_key)
    try:
        result = apply_analysis_result(
            mode,
            classification=payload.classification,
            details=payload.model_dump(mode="json"),
            now=datetime.now(UTC),
        )
    except _FLOW_ERRORS as error:
        session.rollback()
        _raise_flow_conflict(error)

    return _commit_transition(session, mode, result)


@router.post("/{instance_key}/cleaning-complete", response_model=ModeTransitionResponse)
def complete_cleaning(
    instance_key: str,
    session: DatabaseSession,
    response: Response,
) -> ModeTransitionResponse:
    mode = _require_mode(session, instance_key)
    try:
        if mode.enabled and read_cleanliness_state(mode) is CleanlinessState.VERIFYING:
            return _replayed_transition(mode, response)
        result = request_cleaning_verification(mode)
    except _FLOW_ERRORS as error:
        _raise_flow_conflict(error)

    return _commit_transition(session, mode, result)


def _require_mode(session: Session, instance_key: str) -> Mode:
    try:
        return require_mode(session, instance_key)
    except ModeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


_FLOW_ERRORS = (
    AnalysisResultNotExpected,
    InvalidModeConfiguration,
    InvalidPersistedState,
    InvalidStateTransition,
    ModeDisabled,
    UnsupportedCleanlinessModeType,
)


def _raise_flow_conflict(error: Exception) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def _commit_transition(
    session: Session,
    mode: Mode,
    result: TransitionResult,
) -> ModeTransitionResponse:
    session.commit()
    session.refresh(mode)
    return ModeTransitionResponse(
        mode=ModeResponse.model_validate(mode),
        transition=TransitionSummary(
            previous_state=result.previous_state.value,
            current_state=result.current_state.value,
            trigger=result.trigger.value,
            timer_action=result.timer_action.value,
        ),
    )


def _replayed_transition(mode: Mode, response: Response) -> ModeTransitionResponse:
    response.headers["X-HomeAgent-Idempotent-Replay"] = "true"
    return ModeTransitionResponse(
        mode=ModeResponse.model_validate(mode),
        transition=None,
        replayed=True,
    )
