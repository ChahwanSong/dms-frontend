from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.services.models import TaskRecord, TaskStatus
from app.services.repository import RedisTaskRepository


@pytest.mark.asyncio
async def test_save_applies_ttl_to_all_keys() -> None:
    reader = Mock()
    writer = Mock()
    writer.set = AsyncMock(return_value=True)
    writer.sadd = AsyncMock(return_value=1)
    writer.expire = AsyncMock(return_value=True)
    writer.hset = AsyncMock(return_value=True)

    repository = RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=1234)
    task = TaskRecord(task_id="1", service="svc", user_id="user", status=TaskStatus.PENDING)

    await repository.save(task)

    assert writer.set.await_count == 1
    set_call = writer.set.await_args
    assert set_call.kwargs["ex"] == 1234

    expire_calls = {call.args for call in writer.expire.await_args_list}
    expected_keys = {
        ("index:tasks", 1234),
        ("index:service:svc", 1234),
        ("index:service:svc:users", 1234),
        ("index:service:svc:user:user", 1234),
        ("task:1:metadata", 1234 + repository._METADATA_TTL_GRACE_SECONDS),
    }
    assert expected_keys.issubset(expire_calls)
    writer.hset.assert_awaited_with(
        "task:1:metadata", mapping={"service": "svc", "user_id": "user"}
    )


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
    writer.set = AsyncMock(return_value=True)
    writer.sadd = AsyncMock(return_value=1)
    writer.expire = AsyncMock(return_value=True)
    writer.hset = AsyncMock(return_value=True)
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
