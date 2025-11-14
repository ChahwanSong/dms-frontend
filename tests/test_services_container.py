from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, Mock

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
    def __init__(self, *, reader: Any, writer: Any) -> None:
        self.reader = reader
        self.writer = writer


@pytest.fixture(autouse=True)
def _reset_services_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services_container, "configure_logging", lambda settings: None)
    monkeypatch.setattr(services_container, "TaskEventProcessor", _StubEventProcessor)
    monkeypatch.setattr(services_container, "TaskService", _StubTaskService)
    monkeypatch.setattr(services_container, "RedisTaskRepository", _StubRepository)
    services_container._task_service = None
    services_container._event_processor = None
    services_container._scheduler_client = None
    services_container._redis_reader = None
    services_container._redis_writer = None


def _build_settings(**overrides: Any) -> Any:
    defaults = {
        "use_in_memory_store": False,
        "operator_token": "secret",
        "log_json": False,
    }
    defaults.update(overrides)
    return settings_from_overrides(**defaults)


@pytest.mark.asyncio
async def test_init_services_pings_redis(monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture) -> None:
    writer_mock = Mock()
    reader_mock = Mock()
    writer_mock.ping = AsyncMock(return_value=True)
    reader_mock.ping = AsyncMock(return_value=True)
    writer_mock.aclose = AsyncMock(return_value=None)
    reader_mock.aclose = AsyncMock(return_value=None)

    monkeypatch.setattr(
        services_container.Redis,
        "from_url",
        Mock(side_effect=[writer_mock, reader_mock]),
    )

    caplog.set_level(logging.INFO)

    settings = _build_settings()
    scheduler = _StubScheduler()

    await services_container.init_services(settings=settings, scheduler=scheduler)

    assert writer_mock.ping.await_count == 1
    assert reader_mock.ping.await_count == 1
    assert "Successfully connected to Redis" in caplog.text

    await services_container.shutdown_services()


@pytest.mark.asyncio
async def test_init_services_redis_ping_failure(monkeypatch: pytest.MonkeyPatch, caplog: LogCaptureFixture) -> None:
    writer_mock = Mock()
    reader_mock = Mock()
    writer_mock.ping = AsyncMock(side_effect=RuntimeError("redis down"))
    reader_mock.ping = AsyncMock(return_value=True)
    writer_mock.aclose = AsyncMock(return_value=None)
    reader_mock.aclose = AsyncMock(return_value=None)

    monkeypatch.setattr(
        services_container.Redis,
        "from_url",
        Mock(side_effect=[writer_mock, reader_mock]),
    )

    caplog.set_level(logging.INFO)

    settings = _build_settings()
    scheduler = _StubScheduler()

    with pytest.raises(RuntimeError):
        await services_container.init_services(settings=settings, scheduler=scheduler)

    assert "Failed to connect to Redis" in caplog.text
    services_container._redis_reader = None
    services_container._redis_writer = None
