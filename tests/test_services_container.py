from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest import LogCaptureFixture

from app import services_container
from app.core.config import settings_from_overrides


class _StubScheduler:
    async def aclose(self) -> None:  # pragma: no cover - simple stub
        return None


class _StubEventProcessor:
    def __init__(self, repository: Any, scheduler: Any, worker_count: int = 1) -> None:
        self.repository = repository
        self.scheduler = scheduler
        self.worker_count = worker_count
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _StubTaskService:
    def __init__(self, repository: Any, event_processor: Any) -> None:
        self.repository = repository
        self.event_processor = event_processor


class _StubRepository:
    def __init__(self, *, reader: Any, writer: Any, ttl_seconds: int) -> None:
        self.reader = reader
        self.writer = writer
        self.ttl_seconds = ttl_seconds


@pytest.fixture(autouse=True)
def _reset_services_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services_container, "configure_logging", lambda settings: None)
    monkeypatch.setattr(services_container, "TaskEventProcessor", _StubEventProcessor)
    monkeypatch.setattr(services_container, "TaskService", _StubTaskService)
    monkeypatch.setattr(services_container, "RedisRepositoryProvider", _StubRedisProviderFactory)
    services_container._task_service = None
    services_container._event_processor = None
    services_container._scheduler_client = None
    services_container._redis_provider = None


def _build_settings(**overrides: Any) -> Any:
    defaults = {"operator_token": "changeme", "log_json": False}
    defaults.update(overrides)
    return settings_from_overrides(**defaults)


class _StubRedisProviderFactory:
    """Test double replacing :class:`RedisRepositoryProvider`."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.raise_on_get = False
        self.get_repository = AsyncMock(side_effect=self._get_repository)
        self.close = AsyncMock()
        self.start_key_expiration_listener = AsyncMock()

    async def _get_repository(self) -> Any:
        if self.raise_on_get:
            raise RuntimeError("redis down")
        return _StubRepository(reader="reader", writer="writer", ttl_seconds=self.settings.ttl_seconds)


@pytest.mark.asyncio
async def test_init_services_uses_redis_provider(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    settings = _build_settings()
    scheduler = _StubScheduler()

    await services_container.init_services(settings=settings, scheduler=scheduler)

    assert services_container._redis_provider is not None
    stub_provider = services_container._redis_provider
    assert isinstance(stub_provider, _StubRedisProviderFactory)
    stub_provider.get_repository.assert_awaited()
    stub_provider.start_key_expiration_listener.assert_awaited()
    assert "Successfully connected to Redis" in caplog.text

    await services_container.shutdown_services()
    stub_provider.close.assert_awaited()


@pytest.mark.asyncio
async def test_init_services_logs_on_provider_failure(monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture) -> None:
    failing_provider = _StubRedisProviderFactory

    def _factory(settings: Any) -> _StubRedisProviderFactory:
        instance = failing_provider(settings)
        instance.raise_on_get = True
        return instance

    monkeypatch.setattr(services_container, "RedisRepositoryProvider", _factory)  # type: ignore[arg-type]

    caplog.set_level(logging.INFO)

    settings = _build_settings()
    scheduler = _StubScheduler()

    with pytest.raises(RuntimeError):
        await services_container.init_services(settings=settings, scheduler=scheduler)

    assert "Failed to connect to Redis" in caplog.text
    assert services_container._redis_provider is None
