from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="dms_", case_sensitive=False)

    app_name: str = "dms-frontend"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    redis_write_url: str = "redis://haproxy-redis.redis.svc.cluster.local:6379/0"
    redis_read_url: str = "redis://haproxy-redis.redis.svc.cluster.local:6380/0"
    redis_task_ttl_seconds: int = 90 * 24 * 60 * 60

    scheduler_base_url: str = "http://dms-scheduler"
    scheduler_task_endpoint: str = "/task"
    scheduler_cancel_endpoint: str = "/cancel"

    operator_token: str = "changeme"

    event_worker_count: int = 4
    request_timeout_seconds: float = 10.0

    log_level: str = "INFO"
    log_json: bool = True

    cli_default_host: str = "0.0.0.0"
    cli_default_port: int = 8000
    cli_reload: bool = False

    use_in_memory_store: bool = False

    def scheduler_url(self, endpoint: str) -> str:
        base = self.scheduler_base_url.rstrip("/")
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{base}{path}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()  # type: ignore[call-arg]


def settings_from_overrides(**overrides: Any) -> Settings:
    """Utility used in tests to build a settings object from overrides."""

    return Settings(**overrides)
