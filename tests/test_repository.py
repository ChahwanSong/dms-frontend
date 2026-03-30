from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.services.models import TaskRecord, TaskStatus
from app.services.repository import RedisTaskRepository


class _PipelineStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.execute = AsyncMock(return_value=True)

    def set(self, *args, **kwargs) -> None:
        self.calls.append(("set", args, kwargs))

    def hset(self, *args, **kwargs) -> None:
        self.calls.append(("hset", args, kwargs))

    def expire(self, *args, **kwargs) -> None:
        self.calls.append(("expire", args, kwargs))

    def sadd(self, *args, **kwargs) -> None:
        self.calls.append(("sadd", args, kwargs))


class _PipelineContext:
    def __init__(self, pipeline: _PipelineStub) -> None:
        self._pipeline = pipeline

    async def __aenter__(self) -> _PipelineStub:
        return self._pipeline

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_save_applies_ttl_to_all_keys() -> None:
    reader = Mock()
    writer = Mock()
    pipeline = _PipelineStub()
    writer.pipeline = Mock(return_value=_PipelineContext(pipeline))

    repository = RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=1234)
    task = TaskRecord(task_id="1", service="svc", user_id="user", status=TaskStatus.PENDING)

    await repository.save(task)

    writer.pipeline.assert_called_once_with(transaction=True)
    set_calls = [call for call in pipeline.calls if call[0] == "set"]
    assert len(set_calls) == 1
    assert set_calls[0][2]["ex"] == 1234
    assert pipeline.execute.await_count == 1

    expire_calls = {call[1] for call in pipeline.calls if call[0] == "expire"}
    expected_keys = {
        ("index:tasks", 1234),
        ("index:service:svc", 1234),
        ("index:service:svc:users", 1234),
        ("index:service:svc:user:user", 1234),
        ("index:user:user", 1234),
        ("task:1:metadata", 1234 + repository._METADATA_TTL_GRACE_SECONDS),
    }
    assert expected_keys.issubset(expire_calls)

    hset_calls = [call for call in pipeline.calls if call[0] == "hset"]
    assert hset_calls == [
        (
            "hset",
            ("task:1:metadata",),
            {"mapping": {"service": "svc", "user_id": "user"}},
        )
    ]


def test_repository_rejects_non_positive_ttl() -> None:
    reader = Mock()
    writer = Mock()

    with pytest.raises(ValueError):
        RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=0)


@pytest.mark.asyncio
async def test_handle_task_expired_cleans_indexes() -> None:
    reader = Mock()
    writer = Mock()

    reader.hgetall = AsyncMock(return_value={"service": "svc", "user_id": "user"})
    writer.srem = AsyncMock(return_value=1)
    reader.scard = AsyncMock(return_value=0)
    writer.expire = AsyncMock(return_value=True)
    writer.delete = AsyncMock(return_value=1)

    repository = RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=50)

    await repository.handle_task_expired("42")

    writer.srem.assert_any_await("index:tasks", "42")
    writer.srem.assert_any_await("index:service:svc", "42")
    writer.srem.assert_any_await("index:service:svc:user:user", "42")
    writer.delete.assert_awaited_with("task:42:metadata")
    writer.expire.assert_any_await("index:service:svc:users", 50)


@pytest.mark.asyncio
async def test_update_result_merges_fields() -> None:
    reader = Mock()
    writer = Mock()
    writer.incr = AsyncMock(return_value=1)
    pipeline = _PipelineStub()
    writer.pipeline = Mock(return_value=_PipelineContext(pipeline))
    reader.get = AsyncMock(return_value=None)

    repository = RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=999)
    task = TaskRecord(task_id="1", service="svc", user_id="user", status=TaskStatus.PENDING)
    await repository.save(task)

    reader.get = AsyncMock(return_value=task.model_dump_json())

    updated = await repository.update_result(
        "1",
        pod_status="Running",
        launcher_output="stdout",
    )

    assert updated is not None
    assert updated.result.pod_status == "Running"
    assert updated.result.launcher_output == "stdout"


@pytest.mark.asyncio
async def test_delete_cleans_indexes_using_metadata_when_task_payload_missing() -> None:
    reader = Mock()
    writer = Mock()

    reader.get = AsyncMock(return_value=None)
    reader.hgetall = AsyncMock(return_value={"service": "svc", "user_id": "user"})
    reader.scard = AsyncMock(return_value=0)
    writer.srem = AsyncMock(return_value=1)
    writer.expire = AsyncMock(return_value=True)
    writer.delete = AsyncMock(return_value=1)

    repository = RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=111)
    await repository.delete("42")

    writer.srem.assert_any_await("index:tasks", "42")
    writer.srem.assert_any_await("index:service:svc", "42")
    writer.srem.assert_any_await("index:service:svc:user:user", "42")
    writer.srem.assert_any_await("index:user:user", "42")
    writer.delete.assert_awaited_with("task:42:metadata")
