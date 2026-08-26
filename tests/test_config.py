from app.core.config import Settings


def test_default_settings_use_versioned_api_prefix() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_v1_prefix == "/api/v1"
    assert settings.app_env == "development"
    assert settings.database_connect_timeout_seconds == 3
    assert settings.scheduler_enabled is False
    assert settings.scheduler_poll_interval_seconds == 10
    assert settings.scheduler_batch_size == 10
    assert settings.quiet_hours_enabled is True
    assert settings.quiet_hours_timezone == "Asia/Seoul"
    assert settings.quiet_hours_start == "23:00"
    assert settings.quiet_hours_end == "07:00"
