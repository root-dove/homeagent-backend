import pytest

from app.domain.cleanliness import (
    CleanlinessState,
    CleanlinessTrigger,
    InvalidStateTransition,
    TimerAction,
    transition,
)


@pytest.mark.parametrize(
    ("current_state", "trigger", "expected_state", "timer_action"),
    [
        (
            CleanlinessState.MONITORING,
            CleanlinessTrigger.SCHEDULE_DUE,
            CleanlinessState.ANALYZING,
            TimerAction.NONE,
        ),
        (
            CleanlinessState.ANALYZING,
            CleanlinessTrigger.CLEAN_DETECTED,
            CleanlinessState.MONITORING,
            TimerAction.SCHEDULE_MONITORING,
        ),
        (
            CleanlinessState.ANALYZING,
            CleanlinessTrigger.UNCERTAIN_DETECTED,
            CleanlinessState.RETRY_WAIT,
            TimerAction.SCHEDULE_RETRY,
        ),
        (
            CleanlinessState.ANALYZING,
            CleanlinessTrigger.DIRTY_DETECTED,
            CleanlinessState.DIRTY,
            TimerAction.CANCEL,
        ),
        (
            CleanlinessState.ANALYZING,
            CleanlinessTrigger.PROCESSING_FAILED,
            CleanlinessState.ERROR,
            TimerAction.CANCEL,
        ),
        (
            CleanlinessState.RETRY_WAIT,
            CleanlinessTrigger.RETRY_DUE,
            CleanlinessState.ANALYZING,
            TimerAction.NONE,
        ),
        (
            CleanlinessState.DIRTY,
            CleanlinessTrigger.CLEANING_COMPLETED,
            CleanlinessState.VERIFYING,
            TimerAction.CANCEL,
        ),
        (
            CleanlinessState.VERIFYING,
            CleanlinessTrigger.VERIFICATION_PASSED,
            CleanlinessState.MONITORING,
            TimerAction.SCHEDULE_MONITORING,
        ),
        (
            CleanlinessState.VERIFYING,
            CleanlinessTrigger.VERIFICATION_FAILED,
            CleanlinessState.DIRTY,
            TimerAction.CANCEL,
        ),
        (
            CleanlinessState.VERIFYING,
            CleanlinessTrigger.PROCESSING_FAILED,
            CleanlinessState.ERROR,
            TimerAction.CANCEL,
        ),
        (
            CleanlinessState.ERROR,
            CleanlinessTrigger.RETRY_REQUESTED,
            CleanlinessState.ANALYZING,
            TimerAction.NONE,
        ),
        (
            CleanlinessState.ERROR,
            CleanlinessTrigger.RESET_REQUESTED,
            CleanlinessState.MONITORING,
            TimerAction.SCHEDULE_MONITORING,
        ),
    ],
)
def test_allowed_transition(
    current_state: CleanlinessState,
    trigger: CleanlinessTrigger,
    expected_state: CleanlinessState,
    timer_action: TimerAction,
) -> None:
    result = transition(current_state, trigger)

    assert result.previous_state is current_state
    assert result.current_state is expected_state
    assert result.trigger is trigger
    assert result.timer_action is timer_action


def test_dirty_state_rejects_regular_schedule() -> None:
    with pytest.raises(InvalidStateTransition) as error:
        transition(CleanlinessState.DIRTY, CleanlinessTrigger.SCHEDULE_DUE)

    assert error.value.current_state is CleanlinessState.DIRTY
    assert error.value.trigger is CleanlinessTrigger.SCHEDULE_DUE


def test_verification_cannot_start_from_monitoring() -> None:
    with pytest.raises(InvalidStateTransition):
        transition(
            CleanlinessState.MONITORING,
            CleanlinessTrigger.CLEANING_COMPLETED,
        )
