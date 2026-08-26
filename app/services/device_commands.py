from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cleanliness import CleanlinessState, CleanlinessTrigger
from app.models import Device, ModeRun
from app.services.cleanliness_state import transition_cleanliness_mode
from app.services.scheduler import ModeRunStatus


class CommandNotFound(LookupError):
    pass


class CommandConflict(ValueError):
    pass


class CommandLeaseExpired(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimedCommand:
    run: ModeRun
    mode_instance_key: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    run: ModeRun
    mode_runtime_state: str
    replayed: bool = False
    retry_scheduled: bool = False


def claim_commands(
    session: Session,
    *,
    device: Device,
    now: datetime,
    limit: int,
    lease_seconds: int,
    max_attempts: int,
) -> list[ClaimedCommand]:
    _validate_positive("limit", limit)
    _validate_positive("lease_seconds", lease_seconds)
    _validate_positive("max_attempts", max_attempts)
    expired_count = requeue_expired_commands(session, now=now, max_attempts=max_attempts)
    if expired_count:
        # The application session disables autoflush. Persist requeued leases so
        # the following SQL query can claim them in the same transaction.
        session.flush()

    statement = (
        select(ModeRun)
        .where(
            ModeRun.status == ModeRunStatus.QUEUED.value,
            ModeRun.attempt_count < max_attempts,
        )
        .order_by(ModeRun.created_at, ModeRun.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    runs = list(session.scalars(statement))
    commands: list[ClaimedCommand] = []
    for run in runs:
        run.status = ModeRunStatus.PROCESSING.value
        run.assigned_device_id = device.id
        run.started_at = now
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.attempt_count += 1
        run.error_message = None
        commands.append(ClaimedCommand(run=run, mode_instance_key=run.mode.instance_key))
    return commands


def complete_command(
    session: Session,
    *,
    device: Device,
    run_id: UUID,
    now: datetime,
) -> CommandResult:
    run = _locked_run(session, run_id)
    if run.status == ModeRunStatus.COMPLETED.value and run.assigned_device_id == device.id:
        return CommandResult(
            run=run,
            mode_runtime_state=run.mode.runtime_state,
            replayed=True,
        )
    _require_active_assignment(run, device=device, now=now)
    run.status = ModeRunStatus.COMPLETED.value
    run.completed_at = now
    run.lease_expires_at = None
    run.error_message = None
    return CommandResult(run=run, mode_runtime_state=run.mode.runtime_state)


def fail_command(
    session: Session,
    *,
    device: Device,
    run_id: UUID,
    now: datetime,
    error_message: str,
    retryable: bool,
    max_attempts: int,
) -> CommandResult:
    _validate_positive("max_attempts", max_attempts)
    run = _locked_run(session, run_id)
    if run.status == ModeRunStatus.FAILED.value and run.assigned_device_id == device.id:
        return CommandResult(
            run=run,
            mode_runtime_state=run.mode.runtime_state,
            replayed=True,
        )
    _require_active_assignment(run, device=device, now=now)
    run.error_message = error_message

    if retryable and run.attempt_count < max_attempts:
        _reset_for_retry(run)
        return CommandResult(
            run=run,
            mode_runtime_state=run.mode.runtime_state,
            retry_scheduled=True,
        )

    _mark_failed(session, run, now=now, reason=error_message)
    return CommandResult(run=run, mode_runtime_state=run.mode.runtime_state)


def requeue_expired_commands(
    session: Session,
    *,
    now: datetime,
    max_attempts: int,
) -> int:
    statement = (
        select(ModeRun)
        .where(
            ModeRun.status == ModeRunStatus.PROCESSING.value,
            ModeRun.lease_expires_at.is_not(None),
            ModeRun.lease_expires_at <= now,
        )
        .order_by(ModeRun.lease_expires_at, ModeRun.id)
        .with_for_update(skip_locked=True)
    )
    runs = list(session.scalars(statement))
    for run in runs:
        if run.attempt_count < max_attempts:
            run.error_message = "Command lease expired."
            _reset_for_retry(run)
        else:
            _mark_failed(session, run, now=now, reason="Command lease expired.")
    return len(runs)


def _locked_run(session: Session, run_id: UUID) -> ModeRun:
    statement = select(ModeRun).where(ModeRun.id == run_id).with_for_update()
    run = session.scalar(statement)
    if run is None:
        raise CommandNotFound(f"Command '{run_id}' does not exist.")
    return run


def _require_active_assignment(run: ModeRun, *, device: Device, now: datetime) -> None:
    if run.status != ModeRunStatus.PROCESSING.value or run.assigned_device_id != device.id:
        raise CommandConflict(f"Command '{run.id}' is not assigned to this device.")
    lease_expires_at = run.lease_expires_at
    if lease_expires_at is not None and lease_expires_at.tzinfo is None and now.tzinfo is not None:
        # SQLite does not preserve timezone information even for timezone-aware
        # DateTime columns. Stored lease times are UTC, so restore the caller's
        # timezone before comparing them.
        lease_expires_at = lease_expires_at.replace(tzinfo=now.tzinfo)
    if lease_expires_at is None or lease_expires_at <= now:
        raise CommandLeaseExpired(f"Command '{run.id}' lease has expired.")


def _reset_for_retry(run: ModeRun) -> None:
    run.status = ModeRunStatus.QUEUED.value
    run.assigned_device_id = None
    run.started_at = None
    run.lease_expires_at = None


def _mark_failed(session: Session, run: ModeRun, *, now: datetime, reason: str) -> None:
    run.status = ModeRunStatus.FAILED.value
    run.completed_at = now
    run.lease_expires_at = None
    run.error_message = reason
    session.refresh(run.mode, with_for_update=True)
    if run.mode.runtime_state == CleanlinessState.ANALYZING.value:
        transition_cleanliness_mode(
            run.mode,
            CleanlinessTrigger.PROCESSING_FAILED,
            details={"run_id": str(run.id), "error": reason},
        )


def _validate_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"'{name}' must be positive.")
