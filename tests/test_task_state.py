from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from task_state.redis import RedisRepositoryProvider, RedisRepositorySettings


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
