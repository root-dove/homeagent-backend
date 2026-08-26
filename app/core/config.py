from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HomeAgent Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    docs_enabled: bool = True

    database_url: str = "postgresql+psycopg://homeagent:homeagent@localhost:5432/homeagent"
    database_echo: bool = False
    database_connect_timeout_seconds: int = 3

    scheduler_enabled: bool = False
    scheduler_poll_interval_seconds: float = Field(default=10, gt=0)
    scheduler_batch_size: int = Field(default=10, gt=0)
    quiet_hours_enabled: bool = True
    quiet_hours_timezone: str = "Asia/Seoul"
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"

    device_registration_token: str | None = None
    device_offline_after_seconds: int = Field(default=90, gt=0)
    device_command_lease_seconds: int = Field(default=120, gt=0)
    device_command_max_attempts: int = Field(default=3, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
