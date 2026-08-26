from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.scheduling import QuietHoursPolicy
from app.scheduler import PersistentScheduler


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    quiet_hours = None
    if settings.quiet_hours_enabled:
        quiet_hours = QuietHoursPolicy.from_strings(
            timezone_name=settings.quiet_hours_timezone,
            start=settings.quiet_hours_start,
            end=settings.quiet_hours_end,
        )

    scheduler = PersistentScheduler(
        session_factory=SessionLocal,
        poll_interval_seconds=settings.scheduler_poll_interval_seconds,
        batch_size=settings.scheduler_batch_size,
        default_quiet_hours=quiet_hours,
    )
    application.state.scheduler = scheduler
    if settings.scheduler_enabled:
        await scheduler.start()
    try:
        yield
    finally:
        if settings.scheduler_enabled:
            await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
