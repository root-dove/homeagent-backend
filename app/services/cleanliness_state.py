from typing import Any

from app.domain.cleanliness import (
    CleanlinessState,
    CleanlinessTrigger,
    TimerAction,
    TransitionResult,
    transition,
)
from app.models import Mode, ModeStateHistory

CLEANLINESS_MODE_TYPE = "cleanliness"


class UnsupportedModeType(ValueError):
    pass


class InvalidPersistedState(ValueError):
    pass


def transition_cleanliness_mode(
    mode: Mode,
    trigger: CleanlinessTrigger,
    *,
    details: dict[str, Any] | None = None,
) -> tuple[TransitionResult, ModeStateHistory]:
    current_state = read_cleanliness_state(mode)

    result = transition(current_state, trigger)
    history = ModeStateHistory(
        previous_state=result.previous_state.value,
        current_state=result.current_state.value,
        trigger=result.trigger.value,
        details=details or {},
    )
    mode.state_history.append(history)

    mode.runtime_state = result.current_state.value
    mode.state_version = (mode.state_version or 0) + 1

    if result.timer_action is TimerAction.CANCEL:
        mode.next_run_at = None

    return result, history


def read_cleanliness_state(mode: Mode) -> CleanlinessState:
    if mode.mode_type != CLEANLINESS_MODE_TYPE:
        raise UnsupportedModeType(
            f"Mode '{mode.instance_key}' has unsupported type '{mode.mode_type}'."
        )

    try:
        current_state = CleanlinessState(mode.runtime_state)
    except ValueError as error:
        raise InvalidPersistedState(
            f"Mode '{mode.instance_key}' has invalid state '{mode.runtime_state}'."
        ) from error
    return current_state
