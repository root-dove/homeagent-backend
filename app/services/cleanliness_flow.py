from datetime import datetime, timedelta
from typing import Any

from app.domain.cleanliness import (
    AnalysisClassification,
    CleanlinessState,
    CleanlinessTrigger,
    InvalidStateTransition,
    TimerAction,
    TransitionResult,
)
from app.models import Mode
from app.services.cleanliness_state import (
    read_cleanliness_state,
    transition_cleanliness_mode,
)

DEFAULT_MONITORING_INTERVAL_MINUTES = 30
DEFAULT_RETRY_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 24 * 60


class ModeDisabled(ValueError):
    pass


class AnalysisResultNotExpected(ValueError):
    pass


class InvalidModeConfiguration(ValueError):
    pass


def start_analysis(mode: Mode) -> TransitionResult:
    _require_enabled(mode)
    current_state = read_cleanliness_state(mode)
    trigger_by_state = {
        CleanlinessState.MONITORING: CleanlinessTrigger.SCHEDULE_DUE,
        CleanlinessState.RETRY_WAIT: CleanlinessTrigger.RETRY_DUE,
    }
    trigger = trigger_by_state.get(current_state)
    if trigger is None:
        raise InvalidStateTransition(current_state, CleanlinessTrigger.SCHEDULE_DUE)

    result, _ = transition_cleanliness_mode(mode, trigger)
    mode.next_run_at = None
    return result


def request_cleaning_verification(mode: Mode) -> TransitionResult:
    _require_enabled(mode)
    result, _ = transition_cleanliness_mode(
        mode,
        CleanlinessTrigger.CLEANING_COMPLETED,
    )
    return result


def apply_analysis_result(
    mode: Mode,
    *,
    classification: AnalysisClassification,
    details: dict[str, Any],
    now: datetime,
) -> TransitionResult:
    _require_enabled(mode)
    current_state = read_cleanliness_state(mode)
    trigger = _result_trigger(current_state, classification)
    result, _ = transition_cleanliness_mode(mode, trigger, details=details)
    _apply_timer_action(mode, result.timer_action, now=now)
    return result


def _result_trigger(
    current_state: CleanlinessState,
    classification: AnalysisClassification,
) -> CleanlinessTrigger:
    if current_state is CleanlinessState.ANALYZING:
        return {
            AnalysisClassification.CLEAN: CleanlinessTrigger.CLEAN_DETECTED,
            AnalysisClassification.UNCERTAIN: CleanlinessTrigger.UNCERTAIN_DETECTED,
            AnalysisClassification.DIRTY: CleanlinessTrigger.DIRTY_DETECTED,
        }[classification]

    if current_state is CleanlinessState.VERIFYING:
        if classification is AnalysisClassification.CLEAN:
            return CleanlinessTrigger.VERIFICATION_PASSED
        return CleanlinessTrigger.VERIFICATION_FAILED

    raise AnalysisResultNotExpected(
        f"Analysis result is not expected while mode is '{current_state.value}'."
    )


def _apply_timer_action(mode: Mode, action: TimerAction, *, now: datetime) -> None:
    if action is TimerAction.SCHEDULE_MONITORING:
        minutes = _positive_minutes(
            mode,
            "interval_minutes",
            DEFAULT_MONITORING_INTERVAL_MINUTES,
        )
        mode.next_run_at = now + timedelta(minutes=minutes)
    elif action is TimerAction.SCHEDULE_RETRY:
        minutes = _positive_minutes(
            mode,
            "retry_interval_minutes",
            DEFAULT_RETRY_INTERVAL_MINUTES,
        )
        mode.next_run_at = now + timedelta(minutes=minutes)


def _positive_minutes(mode: Mode, key: str, default: int) -> float:
    value = mode.config.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
        or value > MAX_INTERVAL_MINUTES
    ):
        raise InvalidModeConfiguration(f"Mode '{mode.instance_key}' has invalid '{key}' value.")
    return float(value)


def _require_enabled(mode: Mode) -> None:
    if not mode.enabled:
        raise ModeDisabled(f"Mode '{mode.instance_key}' is disabled.")
