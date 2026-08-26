from app.core.config import Settings


def test_default_settings_use_versioned_api_prefix() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_v1_prefix == "/api/v1"
    assert settings.app_env == "development"
    assert settings.database_connect_timeout_seconds == 3
