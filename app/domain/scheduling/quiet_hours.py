from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class QuietHoursConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QuietHoursPolicy:
    timezone_name: str
    start: time
    end: time

    @classmethod
    def from_strings(
        cls,
        *,
        timezone_name: str,
        start: str,
        end: str,
    ) -> "QuietHoursPolicy":
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise QuietHoursConfigurationError(
                f"Unknown quiet-hours timezone '{timezone_name}'."
            ) from error

        start_time = _parse_clock_time(start, "start")
        end_time = _parse_clock_time(end, "end")
        if start_time == end_time:
            raise QuietHoursConfigurationError("Quiet-hours start and end must be different.")
        return cls(timezone_name=timezone_name, start=start_time, end=end_time)


def resolve_quiet_hours_policy(
    config: dict[str, Any],
    default: QuietHoursPolicy | None,
) -> QuietHoursPolicy | None:
    raw_policy = config.get("quiet_hours")
    if raw_policy is None:
        return default
    if not isinstance(raw_policy, dict):
        raise QuietHoursConfigurationError("'quiet_hours' must be an object.")

    enabled = raw_policy.get("enabled", True)
    if not isinstance(enabled, bool):
        raise QuietHoursConfigurationError("'quiet_hours.enabled' must be a boolean.")
    if not enabled:
        return None

    timezone_name = _configured_string(raw_policy, "timezone", default, "timezone_name")
    start = _configured_clock(raw_policy, "start", default)
    end = _configured_clock(raw_policy, "end", default)
    return QuietHoursPolicy.from_strings(
        timezone_name=timezone_name,
        start=start,
        end=end,
    )


def next_allowed_at(now: datetime, policy: QuietHoursPolicy | None) -> datetime | None:
    if policy is None:
        return None
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("'now' must be timezone-aware.")

    timezone = ZoneInfo(policy.timezone_name)
    local_now = now.astimezone(timezone)
    current_time = local_now.timetz().replace(tzinfo=None)
    end_date = _quiet_end_date(
        local_now.date(),
        current_time,
        policy.start,
        policy.end,
    )
    if end_date is None:
        return None

    local_end = datetime.combine(end_date, policy.end, tzinfo=timezone)
    return local_end.astimezone(UTC)


def _quiet_end_date(
    current_date: date,
    current_time: time,
    start: time,
    end: time,
) -> date | None:
    if start < end:
        if start <= current_time < end:
            return current_date
        return None

    if current_time >= start:
        return current_date + timedelta(days=1)
    if current_time < end:
        return current_date
    return None


def _parse_clock_time(value: str, field_name: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise QuietHoursConfigurationError(
            f"Quiet-hours {field_name} must use HH:MM format."
        ) from error
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise QuietHoursConfigurationError(f"Quiet-hours {field_name} must use HH:MM format.")
    return parsed


def _configured_string(
    raw_policy: dict[str, Any],
    key: str,
    default: QuietHoursPolicy | None,
    default_attribute: str,
) -> str:
    value = raw_policy.get(key)
    if value is None and default is not None:
        value = getattr(default, default_attribute)
    if not isinstance(value, str) or not value:
        raise QuietHoursConfigurationError(f"'quiet_hours.{key}' must be a string.")
    return value


def _configured_clock(
    raw_policy: dict[str, Any],
    key: str,
    default: QuietHoursPolicy | None,
) -> str:
    value = raw_policy.get(key)
    if value is None and default is not None:
        value = getattr(default, key).strftime("%H:%M")
    if not isinstance(value, str):
        raise QuietHoursConfigurationError(f"'quiet_hours.{key}' must be a string.")
    return value
