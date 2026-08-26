from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Capture, Device, ModeRun
from app.services.device_commands import (
    CommandConflict,
    locked_command,
    require_active_assignment,
)


class InvalidCapturedAt(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    run: ModeRun
    existing: Capture | None = None


def prepare_capture_target(
    session: Session,
    *,
    device: Device,
    run_id: UUID,
    now: datetime,
) -> CaptureTarget:
    run = locked_command(session, run_id)
    existing = session.scalar(select(Capture).where(Capture.run_id == run_id))
    if existing is not None:
        if existing.device_id != device.id:
            raise CommandConflict(f"Capture for command '{run_id}' belongs to another device.")
        return CaptureTarget(run=run, existing=existing)
    require_active_assignment(run, device=device, now=now)
    return CaptureTarget(run=run)


def normalize_captured_at(value: datetime, *, now: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidCapturedAt("captured_at must include a timezone offset.")
    normalized = value.astimezone(UTC)
    if normalized > now + timedelta(minutes=5):
        raise InvalidCapturedAt("captured_at is too far in the future.")
    if normalized < now - timedelta(days=1):
        raise InvalidCapturedAt("captured_at is older than one day.")
    return normalized
