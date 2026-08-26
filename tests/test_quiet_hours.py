from datetime import UTC, datetime

import pytest

from app.domain.scheduling import (
    QuietHoursConfigurationError,
    QuietHoursPolicy,
    next_allowed_at,
    resolve_quiet_hours_policy,
)


@pytest.fixture
def overnight_policy() -> QuietHoursPolicy:
    return QuietHoursPolicy.from_strings(
        timezone_name="Asia/Seoul",
        start="23:00",
        end="07:00",
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 8, 26, 14, 0, tzinfo=UTC),  # 23:00 KST
            datetime(2026, 8, 26, 22, 0, tzinfo=UTC),  # 07:00 KST next day
        ),
        (
            datetime(2026, 8, 26, 17, 0, tzinfo=UTC),  # 02:00 KST
            datetime(2026, 8, 26, 22, 0, tzinfo=UTC),  # 07:00 KST
        ),
    ],
)
def test_overnight_quiet_hours_return_next_allowed_time(
    overnight_policy: QuietHoursPolicy,
    now: datetime,
    expected: datetime,
) -> None:
    assert next_allowed_at(now, overnight_policy) == expected


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 8, 26, 13, 59, tzinfo=UTC),  # 22:59 KST
        datetime(2026, 8, 26, 22, 0, tzinfo=UTC),  # 07:00 KST
    ],
)
def test_overnight_quiet_hours_allow_boundary_times(
    overnight_policy: QuietHoursPolicy,
    now: datetime,
) -> None:
    assert next_allowed_at(now, overnight_policy) is None


def test_same_day_quiet_hours_are_supported() -> None:
    policy = QuietHoursPolicy.from_strings(
        timezone_name="Asia/Seoul",
        start="13:00",
        end="14:00",
    )

    assert next_allowed_at(
        datetime(2026, 8, 26, 4, 30, tzinfo=UTC),
        policy,
    ) == datetime(2026, 8, 26, 5, 0, tzinfo=UTC)


def test_mode_can_disable_default_quiet_hours(
    overnight_policy: QuietHoursPolicy,
) -> None:
    resolved = resolve_quiet_hours_policy(
        {"quiet_hours": {"enabled": False}},
        overnight_policy,
    )

    assert resolved is None


def test_mode_can_override_default_quiet_hours(
    overnight_policy: QuietHoursPolicy,
) -> None:
    resolved = resolve_quiet_hours_policy(
        {"quiet_hours": {"start": "01:00", "end": "06:30"}},
        overnight_policy,
    )

    assert resolved is not None
    assert resolved.start.isoformat(timespec="minutes") == "01:00"
    assert resolved.end.isoformat(timespec="minutes") == "06:30"
    assert resolved.timezone_name == "Asia/Seoul"


@pytest.mark.parametrize(
    ("start", "end"),
    [("23:00", "23:00"), ("25:00", "07:00"), ("23:00:01", "07:00")],
)
def test_invalid_quiet_hours_are_rejected(start: str, end: str) -> None:
    with pytest.raises(QuietHoursConfigurationError):
        QuietHoursPolicy.from_strings(
            timezone_name="Asia/Seoul",
            start=start,
            end=end,
        )


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(QuietHoursConfigurationError, match="Unknown"):
        QuietHoursPolicy.from_strings(
            timezone_name="Moon/Base",
            start="23:00",
            end="07:00",
        )


@pytest.mark.parametrize(
    "config",
    [
        {"quiet_hours": "23:00-07:00"},
        {"quiet_hours": {"enabled": "yes"}},
        {"quiet_hours": {"enabled": True}},
    ],
)
def test_invalid_mode_override_is_rejected(config: dict[str, object]) -> None:
    with pytest.raises(QuietHoursConfigurationError):
        resolve_quiet_hours_policy(config, default=None)


def test_next_allowed_at_requires_timezone_aware_now(
    overnight_policy: QuietHoursPolicy,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        next_allowed_at(datetime(2026, 8, 26, 23, 0), overnight_policy)
