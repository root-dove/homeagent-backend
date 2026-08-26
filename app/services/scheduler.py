from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cleanliness import CleanlinessState
from app.domain.scheduling import (
    QuietHoursConfigurationError,
    QuietHoursPolicy,
    next_allowed_at,
    resolve_quiet_hours_policy,
)
from app.models import Mode, ModeRun
from app.services.cleanliness_flow import start_analysis

SCHEDULER_CONFIGURATION_RETRY_MINUTES = 5


class ModeRunStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SchedulerAction(StrEnum):
    QUEUED = "queued"
    DEFERRED_QUIET_HOURS = "deferred_quiet_hours"
    DEFERRED_CONFIGURATION_ERROR = "deferred_configuration_error"


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    mode_id: str
    instance_key: str
    action: SchedulerAction
    next_run_at: datetime | None
    run_id: str | None = None
    message: str | None = None


def claim_due_modes(
    session: Session,
    *,
    now: datetime,
    default_quiet_hours: QuietHoursPolicy | None,
    batch_size: int,
) -> list[SchedulerDecision]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("'now' must be timezone-aware.")
    if batch_size <= 0:
        raise ValueError("'batch_size' must be positive.")

    due_states = [CleanlinessState.MONITORING.value, CleanlinessState.RETRY_WAIT.value]
    statement = (
        select(Mode)
        .where(
            Mode.enabled.is_(True),
            Mode.runtime_state.in_(due_states),
            Mode.next_run_at.is_not(None),
            Mode.next_run_at <= now,
        )
        .order_by(Mode.next_run_at, Mode.instance_key)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    modes = list(session.scalars(statement))
    return [
        _process_due_mode(
            mode,
            now=now,
            default_quiet_hours=default_quiet_hours,
        )
        for mode in modes
    ]


def list_queued_runs(session: Session, *, limit: int = 100) -> list[ModeRun]:
    if limit <= 0:
        raise ValueError("'limit' must be positive.")
    statement = (
        select(ModeRun)
        .where(ModeRun.status == ModeRunStatus.QUEUED.value)
        .order_by(ModeRun.created_at, ModeRun.id)
        .limit(limit)
    )
    return list(session.scalars(statement))


def _process_due_mode(
    mode: Mode,
    *,
    now: datetime,
    default_quiet_hours: QuietHoursPolicy | None,
) -> SchedulerDecision:
    scheduled_for = mode.next_run_at
    if scheduled_for is None:
        raise ValueError(f"Mode '{mode.instance_key}' has no scheduled run.")

    try:
        quiet_policy = resolve_quiet_hours_policy(mode.config, default_quiet_hours)
        quiet_end = next_allowed_at(now, quiet_policy)
    except QuietHoursConfigurationError as error:
        mode.next_run_at = now + timedelta(minutes=SCHEDULER_CONFIGURATION_RETRY_MINUTES)
        mode.state_version = (mode.state_version or 0) + 1
        return SchedulerDecision(
            mode_id=str(mode.id),
            instance_key=mode.instance_key,
            action=SchedulerAction.DEFERRED_CONFIGURATION_ERROR,
            next_run_at=mode.next_run_at,
            message=str(error),
        )

    if quiet_end is not None:
        mode.next_run_at = quiet_end
        mode.state_version = (mode.state_version or 0) + 1
        return SchedulerDecision(
            mode_id=str(mode.id),
            instance_key=mode.instance_key,
            action=SchedulerAction.DEFERRED_QUIET_HOURS,
            next_run_at=quiet_end,
        )

    transition = start_analysis(mode)
    run_id = uuid4()
    run = ModeRun(
        id=run_id,
        mode_state_version=mode.state_version,
        trigger=transition.trigger.value,
        status=ModeRunStatus.QUEUED.value,
        scheduled_for=scheduled_for,
    )
    mode.runs.append(run)
    return SchedulerDecision(
        mode_id=str(mode.id),
        instance_key=mode.instance_key,
        action=SchedulerAction.QUEUED,
        next_run_at=None,
        run_id=str(run_id),
    )
