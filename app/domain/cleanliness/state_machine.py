from dataclasses import dataclass
from enum import StrEnum


class CleanlinessState(StrEnum):
    MONITORING = "monitoring"
    ANALYZING = "analyzing"
    RETRY_WAIT = "retry_wait"
    DIRTY = "dirty"
    VERIFYING = "verifying"
    ERROR = "error"


class CleanlinessTrigger(StrEnum):
    SCHEDULE_DUE = "schedule_due"
    CLEAN_DETECTED = "clean_detected"
    UNCERTAIN_DETECTED = "uncertain_detected"
    DIRTY_DETECTED = "dirty_detected"
    RETRY_DUE = "retry_due"
    CLEANING_COMPLETED = "cleaning_completed"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    PROCESSING_FAILED = "processing_failed"
    RETRY_REQUESTED = "retry_requested"
    RESET_REQUESTED = "reset_requested"


class TimerAction(StrEnum):
    NONE = "none"
    CANCEL = "cancel"
    SCHEDULE_MONITORING = "schedule_monitoring"
    SCHEDULE_RETRY = "schedule_retry"


@dataclass(frozen=True, slots=True)
class TransitionRule:
    next_state: CleanlinessState
    timer_action: TimerAction = TimerAction.NONE


@dataclass(frozen=True, slots=True)
class TransitionResult:
    previous_state: CleanlinessState
    current_state: CleanlinessState
    trigger: CleanlinessTrigger
    timer_action: TimerAction


class InvalidStateTransition(ValueError):
    def __init__(
        self,
        current_state: CleanlinessState,
        trigger: CleanlinessTrigger,
    ) -> None:
        self.current_state = current_state
        self.trigger = trigger
        super().__init__(
            f"Transition '{trigger.value}' is not allowed from '{current_state.value}'."
        )


_TRANSITIONS: dict[
    tuple[CleanlinessState, CleanlinessTrigger],
    TransitionRule,
] = {
    (CleanlinessState.MONITORING, CleanlinessTrigger.SCHEDULE_DUE): TransitionRule(
        CleanlinessState.ANALYZING
    ),
    (CleanlinessState.ANALYZING, CleanlinessTrigger.CLEAN_DETECTED): TransitionRule(
        CleanlinessState.MONITORING,
        TimerAction.SCHEDULE_MONITORING,
    ),
    (CleanlinessState.ANALYZING, CleanlinessTrigger.UNCERTAIN_DETECTED): TransitionRule(
        CleanlinessState.RETRY_WAIT,
        TimerAction.SCHEDULE_RETRY,
    ),
    (CleanlinessState.ANALYZING, CleanlinessTrigger.DIRTY_DETECTED): TransitionRule(
        CleanlinessState.DIRTY,
        TimerAction.CANCEL,
    ),
    (CleanlinessState.ANALYZING, CleanlinessTrigger.PROCESSING_FAILED): TransitionRule(
        CleanlinessState.ERROR,
        TimerAction.CANCEL,
    ),
    (CleanlinessState.RETRY_WAIT, CleanlinessTrigger.RETRY_DUE): TransitionRule(
        CleanlinessState.ANALYZING
    ),
    (CleanlinessState.DIRTY, CleanlinessTrigger.CLEANING_COMPLETED): TransitionRule(
        CleanlinessState.VERIFYING,
        TimerAction.CANCEL,
    ),
    (CleanlinessState.VERIFYING, CleanlinessTrigger.VERIFICATION_PASSED): TransitionRule(
        CleanlinessState.MONITORING,
        TimerAction.SCHEDULE_MONITORING,
    ),
    (CleanlinessState.VERIFYING, CleanlinessTrigger.VERIFICATION_FAILED): TransitionRule(
        CleanlinessState.DIRTY,
        TimerAction.CANCEL,
    ),
    (CleanlinessState.VERIFYING, CleanlinessTrigger.PROCESSING_FAILED): TransitionRule(
        CleanlinessState.ERROR,
        TimerAction.CANCEL,
    ),
    (CleanlinessState.ERROR, CleanlinessTrigger.RETRY_REQUESTED): TransitionRule(
        CleanlinessState.ANALYZING
    ),
    (CleanlinessState.ERROR, CleanlinessTrigger.RESET_REQUESTED): TransitionRule(
        CleanlinessState.MONITORING,
        TimerAction.SCHEDULE_MONITORING,
    ),
}


def transition(
    current_state: CleanlinessState,
    trigger: CleanlinessTrigger,
) -> TransitionResult:
    rule = _TRANSITIONS.get((current_state, trigger))
    if rule is None:
        raise InvalidStateTransition(current_state, trigger)

    return TransitionResult(
        previous_state=current_state,
        current_state=rule.next_state,
        trigger=trigger,
        timer_action=rule.timer_action,
    )
