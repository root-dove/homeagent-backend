from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.domain.cleanliness import (
    CleanlinessState,
    CleanlinessTrigger,
    TimerAction,
)
from app.models import Mode, ModeStateHistory
from app.services.cleanliness_state import (
    InvalidPersistedState,
    UnsupportedModeType,
    transition_cleanliness_mode,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def create_cleanliness_mode(**overrides: object) -> Mode:
    values: dict[str, object] = {
        "instance_key": "bedroom-cleanliness",
        "mode_type": "cleanliness",
        "name": "청결 모드",
        "enabled": True,
        "runtime_state": CleanlinessState.ANALYZING.value,
        "next_run_at": datetime(2026, 8, 26, 14, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return Mode(**values)


def test_dirty_transition_is_persisted_and_cancels_timer(session: Session) -> None:
    mode = create_cleanliness_mode()
    session.add(mode)

    result, history = transition_cleanliness_mode(
        mode,
        CleanlinessTrigger.DIRTY_DETECTED,
        details={"score": 78},
    )
    session.commit()

    saved_mode = session.scalar(select(Mode).where(Mode.id == mode.id))
    saved_history = session.scalar(
        select(ModeStateHistory).where(ModeStateHistory.mode_id == mode.id)
    )

    assert result.current_state is CleanlinessState.DIRTY
    assert result.timer_action is TimerAction.CANCEL
    assert saved_mode is not None
    assert saved_mode.runtime_state == CleanlinessState.DIRTY.value
    assert saved_mode.next_run_at is None
    assert saved_mode.state_version == 1
    assert saved_history is history
    assert saved_history.previous_state == CleanlinessState.ANALYZING.value
    assert saved_history.current_state == CleanlinessState.DIRTY.value
    assert saved_history.details == {"score": 78}


def test_disabling_mode_does_not_erase_dirty_state(session: Session) -> None:
    mode = create_cleanliness_mode(
        enabled=False,
        runtime_state=CleanlinessState.DIRTY.value,
        next_run_at=None,
    )
    session.add(mode)
    session.commit()

    mode.enabled = True
    session.commit()

    assert mode.enabled is True
    assert mode.runtime_state == CleanlinessState.DIRTY.value
    assert mode.next_run_at is None


def test_transition_rejects_non_cleanliness_mode() -> None:
    mode = create_cleanliness_mode(mode_type="security")

    with pytest.raises(UnsupportedModeType):
        transition_cleanliness_mode(mode, CleanlinessTrigger.DIRTY_DETECTED)


def test_transition_rejects_invalid_persisted_state() -> None:
    mode = create_cleanliness_mode(runtime_state="unknown")

    with pytest.raises(InvalidPersistedState):
        transition_cleanliness_mode(mode, CleanlinessTrigger.DIRTY_DETECTED)
