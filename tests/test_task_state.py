from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from task_state.models import PriorityLevel, TaskRecord, TaskStatus
from task_state.redis import (
    RedisRepositoryProvider,
    RedisRepositorySettings,
    TaskExpirationSubscriber,
)


@pytest.mark.asyncio
async def test_provider_creates_and_reuses_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    writer_mock = Mock()
    reader_mock = Mock()
    writer_mock.ping = AsyncMock(return_value=True)
    reader_mock.ping = AsyncMock(return_value=True)
    writer_mock.aclose = AsyncMock(return_value=None)
    reader_mock.aclose = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "task_state.redis.Redis.from_url",
        Mock(side_effect=[writer_mock, reader_mock]),
    )

    provider = RedisRepositoryProvider(
        RedisRepositorySettings(
            write_url="redis://write", read_url="redis://read", ttl_seconds=60
        )
    )

    repository = await provider.get_repository()
    assert repository is await provider.get_repository()
    assert writer_mock.ping.await_count == 1
    assert reader_mock.ping.await_count == 1

    await provider.close()
    writer_mock.aclose.assert_awaited()
    reader_mock.aclose.assert_awaited()


class _StubPubSub:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages
        self.subscribed: list[str] = []
        self.closed = False

    async def __aenter__(self) -> "_StubPubSub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - passthrough
        await self.aclose()

    async def psubscribe(self, *patterns: str) -> None:
        self.subscribed.extend(patterns)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0) -> dict | None:
        if self.closed:
            return None
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(0)
        return None

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_task_expiration_subscriber_handles_task_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.handle_task_expired = AsyncMock(return_value=None)

    pubsub = _StubPubSub(messages=[{"data": "task:77"}, {"data": "other"}])

    reader = Mock()
    reader.connection_pool = Mock(connection_kwargs={"db": 2})
    reader.pubsub = Mock(return_value=pubsub)

    subscriber = TaskExpirationSubscriber(reader=reader, repository=repository)

    await subscriber.start()
    await asyncio.sleep(0.05)
    await subscriber.stop()

    repository.handle_task_expired.assert_awaited_with("77")
    assert "__keyevent@2__:expired" in pubsub.subscribed


@pytest.mark.asyncio
async def test_provider_closes_clients_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    writer_mock = Mock()
    reader_mock = Mock()
    writer_mock.ping = AsyncMock(side_effect=RuntimeError("redis down"))
    reader_mock.ping = AsyncMock(return_value=True)
    writer_mock.aclose = AsyncMock(return_value=None)
    reader_mock.aclose = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "task_state.redis.Redis.from_url",
        Mock(side_effect=[writer_mock, reader_mock]),
    )

    provider = RedisRepositoryProvider(
        RedisRepositorySettings(
            write_url="redis://write", read_url="redis://read", ttl_seconds=60
        )
    )

    with pytest.raises(RuntimeError):
        await provider.get_repository()

    writer_mock.aclose.assert_awaited()
    reader_mock.aclose.assert_awaited()


def test_task_record_defaults_to_low_priority() -> None:
    record = TaskRecord(
        task_id="123",
        service="service",
        user_id="user",
        status=TaskStatus.PENDING,
    )

    assert record.priority is PriorityLevel.low
    assert record.jobs == []
    assert record.model_dump(mode="json")["priority"] == "low"
