from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cleanliness import CleanlinessState
from app.models import Mode

CLEANLINESS_MODE_TYPE = "cleanliness"

_INITIAL_STATES = {
    CLEANLINESS_MODE_TYPE: CleanlinessState.MONITORING.value,
}


class ModeAlreadyExists(ValueError):
    pass


class ModeNotFound(LookupError):
    pass


class UnsupportedModeType(ValueError):
    pass


def create_mode(
    session: Session,
    *,
    instance_key: str,
    mode_type: str,
    name: str,
    enabled: bool,
    config: dict[str, object],
) -> Mode:
    initial_state = _INITIAL_STATES.get(mode_type)
    if initial_state is None:
        raise UnsupportedModeType(f"Mode type '{mode_type}' is not registered.")

    if get_mode(session, instance_key) is not None:
        raise ModeAlreadyExists(f"Mode '{instance_key}' already exists.")

    mode = Mode(
        instance_key=instance_key,
        mode_type=mode_type,
        name=name,
        enabled=enabled,
        runtime_state=initial_state,
        config=config,
    )
    session.add(mode)
    return mode


def list_modes(session: Session) -> list[Mode]:
    statement = select(Mode).order_by(Mode.instance_key)
    return list(session.scalars(statement))


def get_mode(session: Session, instance_key: str) -> Mode | None:
    statement = select(Mode).where(Mode.instance_key == instance_key)
    return session.scalar(statement)


def require_mode(session: Session, instance_key: str) -> Mode:
    mode = get_mode(session, instance_key)
    if mode is None:
        raise ModeNotFound(f"Mode '{instance_key}' does not exist.")
    return mode


def set_mode_enabled(mode: Mode, *, enabled: bool) -> bool:
    changed = mode.enabled is not enabled
    mode.enabled = enabled

    if not enabled and mode.next_run_at is not None:
        mode.next_run_at = None
        changed = True

    if changed:
        mode.state_version = (mode.state_version or 0) + 1

    return changed
