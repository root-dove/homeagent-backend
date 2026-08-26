from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.config import get_settings
from app.db.session import engine

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    checks: dict[str, Literal["ok", "unavailable"]]


def database_is_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def build_health_response(*, checks: dict[str, Literal["ok", "unavailable"]]) -> HealthResponse:
    settings = get_settings()
    healthy = all(check == "ok" for check in checks.values())
    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        checks=checks,
    )


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return build_health_response(checks={"application": "ok"})


@router.get("", response_model=HealthResponse)
@router.get("/ready", response_model=HealthResponse)
def readiness(
    response: Response,
    database_ready: Annotated[bool, Depends(database_is_ready)],
) -> HealthResponse:
    if not database_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return build_health_response(
        checks={
            "application": "ok",
            "database": "ok" if database_ready else "unavailable",
        }
    )
