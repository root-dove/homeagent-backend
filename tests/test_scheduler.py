import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.domain.cleanliness import CleanlinessState
from app.domain.scheduling import QuietHoursPolicy
from app.models import Mode, ModeRun, ModeStateHistory
from app.scheduler import PersistentScheduler
from app.services.scheduler import (
    ModeRunStatus,
    SchedulerAction,
    claim_due_modes,
    list_queued_runs,
)

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=UTC)  # 02:00 KST


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def quiet_hours() -> QuietHoursPolicy:
    return QuietHoursPolicy.from_strings(
        timezone_name="Asia/Seoul",
        start="23:00",
        end="07:00",
    )


def add_mode(
    session: Session,
    *,
    instance_key: str = "cleanliness",
    enabled: bool = True,
    runtime_state: str = CleanlinessState.MONITORING.value,
    next_run_at: datetime | None = NOW - timedelta(minutes=1),
    config: dict[str, object] | None = None,
) -> Mode:
    mode = Mode(
        instance_key=instance_key,
        mode_type="cleanliness",
        name=instance_key,
        enabled=enabled,
        runtime_state=runtime_state,
        next_run_at=next_run_at,
        config=config or {},
    )
    session.add(mode)
    session.flush()
    return mode


def test_due_mode_is_atomically_queued_outside_quiet_hours(
    session_factory: sessionmaker[Session],
    quiet_hours: QuietHoursPolicy,
) -> None:
    daytime = datetime(2026, 8, 26, 4, 0, tzinfo=UTC)  # 13:00 KST
    with session_factory.begin() as session:
        mode = add_mode(session, next_run_at=daytime - timedelta(minutes=1))
        mode_id = mode.id

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=daytime,
            default_quiet_hours=quiet_hours,
            batch_size=10,
        )

    assert len(decisions) == 1
    assert decisions[0].action is SchedulerAction.QUEUED
    assert decisions[0].run_id is not None

    with session_factory() as session:
        saved_mode = session.get(Mode, mode_id)
        run = session.scalar(select(ModeRun).where(ModeRun.mode_id == mode_id))
        history = session.scalar(
            select(ModeStateHistory).where(ModeStateHistory.mode_id == mode_id)
        )
        assert saved_mode is not None
        assert saved_mode.runtime_state == CleanlinessState.ANALYZING.value
        assert saved_mode.next_run_at is None
        assert saved_mode.state_version == 1
        assert run is not None
        assert run.status == ModeRunStatus.QUEUED.value
        assert run.mode_state_version == 1
        assert run.trigger == "schedule_due"
        assert history is not None
        assert history.current_state == CleanlinessState.ANALYZING.value


def test_quiet_hours_defer_without_changing_runtime_state(
    session_factory: sessionmaker[Session],
    quiet_hours: QuietHoursPolicy,
) -> None:
    with session_factory.begin() as session:
        mode = add_mode(session)
        mode_id = mode.id

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=quiet_hours,
            batch_size=10,
        )

    assert decisions[0].action is SchedulerAction.DEFERRED_QUIET_HOURS
    assert decisions[0].next_run_at == datetime(2026, 8, 26, 22, 0, tzinfo=UTC)
    with session_factory() as session:
        saved_mode = session.get(Mode, mode_id)
        assert saved_mode is not None
        assert saved_mode.runtime_state == CleanlinessState.MONITORING.value
        assert saved_mode.next_run_at == datetime(2026, 8, 26, 22, 0)
        assert saved_mode.state_version == 1
        assert session.scalar(select(ModeRun)) is None


def test_mode_override_can_run_during_global_quiet_hours(
    session_factory: sessionmaker[Session],
    quiet_hours: QuietHoursPolicy,
) -> None:
    with session_factory.begin() as session:
        add_mode(session, config={"quiet_hours": {"enabled": False}})

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=quiet_hours,
            batch_size=10,
        )

    assert decisions[0].action is SchedulerAction.QUEUED


def test_retry_wait_creates_retry_due_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        add_mode(session, runtime_state=CleanlinessState.RETRY_WAIT.value)

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=None,
            batch_size=10,
        )

    assert decisions[0].action is SchedulerAction.QUEUED
    with session_factory() as session:
        run = session.scalar(select(ModeRun))
        assert run is not None
        assert run.trigger == "retry_due"


def test_disabled_dirty_future_and_unscheduled_modes_are_not_claimed(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        add_mode(session, instance_key="disabled", enabled=False)
        add_mode(
            session,
            instance_key="dirty",
            runtime_state=CleanlinessState.DIRTY.value,
        )
        add_mode(
            session,
            instance_key="future",
            next_run_at=NOW + timedelta(minutes=1),
        )
        add_mode(session, instance_key="unscheduled", next_run_at=None)

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=None,
            batch_size=10,
        )

    assert decisions == []


def test_invalid_mode_quiet_hours_are_deferred_for_five_minutes(
    session_factory: sessionmaker[Session],
    quiet_hours: QuietHoursPolicy,
) -> None:
    with session_factory.begin() as session:
        mode = add_mode(session, config={"quiet_hours": {"start": "bad"}})
        mode_id = mode.id

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=quiet_hours,
            batch_size=10,
        )

    assert decisions[0].action is SchedulerAction.DEFERRED_CONFIGURATION_ERROR
    assert decisions[0].next_run_at == NOW + timedelta(minutes=5)
    assert decisions[0].message is not None
    with session_factory() as session:
        saved_mode = session.get(Mode, mode_id)
        assert saved_mode is not None
        assert saved_mode.runtime_state == CleanlinessState.MONITORING.value


def test_batch_size_and_due_order_are_applied(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        add_mode(
            session,
            instance_key="second",
            next_run_at=NOW - timedelta(minutes=1),
        )
        add_mode(
            session,
            instance_key="first",
            next_run_at=NOW - timedelta(minutes=2),
        )

    with session_factory.begin() as session:
        decisions = claim_due_modes(
            session,
            now=NOW,
            default_quiet_hours=None,
            batch_size=1,
        )

    assert [decision.instance_key for decision in decisions] == ["first"]


def test_persistent_scheduler_does_not_duplicate_queued_run_after_restart(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        add_mode(session)

    first_runner = PersistentScheduler(
        session_factory=session_factory,
        poll_interval_seconds=10,
        batch_size=10,
        default_quiet_hours=None,
    )
    second_runner = PersistentScheduler(
        session_factory=session_factory,
        poll_interval_seconds=10,
        batch_size=10,
        default_quiet_hours=None,
    )

    assert len(first_runner.run_once(now=NOW)) == 1
    assert second_runner.run_once(now=NOW) == []
    with session_factory() as session:
        queued = list_queued_runs(session)
        assert len(queued) == 1


@pytest.mark.parametrize("value", [0, -1])
def test_scheduler_rejects_invalid_limits(
    session_factory: sessionmaker[Session],
    value: int,
) -> None:
    with session_factory() as session:
        with pytest.raises(ValueError):
            claim_due_modes(
                session,
                now=NOW,
                default_quiet_hours=None,
                batch_size=value,
            )
        with pytest.raises(ValueError):
            list_queued_runs(session, limit=value)


@pytest.mark.parametrize(
    ("poll_interval_seconds", "batch_size"),
    [(0, 10), (10, 0)],
)
def test_persistent_scheduler_rejects_invalid_configuration(
    session_factory: sessionmaker[Session],
    poll_interval_seconds: float,
    batch_size: int,
) -> None:
    with pytest.raises(ValueError):
        PersistentScheduler(
            session_factory=session_factory,
            poll_interval_seconds=poll_interval_seconds,
            batch_size=batch_size,
            default_quiet_hours=None,
        )


def test_background_scheduler_start_and_stop_are_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    scheduler = PersistentScheduler(
        session_factory=session_factory,
        poll_interval_seconds=0.01,
        batch_size=10,
        default_quiet_hours=None,
    )

    async def exercise() -> None:
        await scheduler.start()
        await scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()
        await scheduler.stop()

    with patch.object(scheduler, "run_once", return_value=[]) as run_once:
        asyncio.run(exercise())

    run_once.assert_called()
