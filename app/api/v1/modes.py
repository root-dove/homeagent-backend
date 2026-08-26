from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models import Mode
from app.schemas import ModeCreate, ModeResponse
from app.services.modes import (
    ModeAlreadyExists,
    ModeNotFound,
    UnsupportedModeType,
    create_mode,
    list_modes,
    require_mode,
    set_mode_enabled,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.post("", response_model=ModeResponse, status_code=status.HTTP_201_CREATED)
def register_mode(payload: ModeCreate, session: DatabaseSession) -> ModeResponse:
    try:
        mode = create_mode(session, **payload.model_dump())
        session.commit()
        session.refresh(mode)
    except ModeAlreadyExists as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except UnsupportedModeType as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mode '{payload.instance_key}' already exists.",
        ) from error

    return ModeResponse.model_validate(mode)


@router.get("", response_model=list[ModeResponse])
def read_modes(session: DatabaseSession) -> list[ModeResponse]:
    return [ModeResponse.model_validate(mode) for mode in list_modes(session)]


@router.get("/{instance_key}", response_model=ModeResponse)
def read_mode(instance_key: str, session: DatabaseSession) -> ModeResponse:
    mode = _require_mode(session, instance_key)
    return ModeResponse.model_validate(mode)


@router.post("/{instance_key}/enable", response_model=ModeResponse)
def enable_mode(instance_key: str, session: DatabaseSession, response: Response) -> ModeResponse:
    mode = _require_mode(session, instance_key)
    if set_mode_enabled(mode, enabled=True):
        session.commit()
        session.refresh(mode)
    else:
        response.headers["X-HomeAgent-Idempotent-Replay"] = "true"
    return ModeResponse.model_validate(mode)


@router.post("/{instance_key}/disable", response_model=ModeResponse)
def disable_mode(instance_key: str, session: DatabaseSession, response: Response) -> ModeResponse:
    mode = _require_mode(session, instance_key)
    if set_mode_enabled(mode, enabled=False):
        session.commit()
        session.refresh(mode)
    else:
        response.headers["X-HomeAgent-Idempotent-Replay"] = "true"
    return ModeResponse.model_validate(mode)


def _require_mode(session: Session, instance_key: str) -> Mode:
    try:
        return require_mode(session, instance_key)
    except ModeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
