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
    }
    assert expected_keys.issubset(expire_calls)


def test_repository_rejects_non_positive_ttl() -> None:
    reader = Mock()
    writer = Mock()

    with pytest.raises(ValueError):
        RedisTaskRepository(reader=reader, writer=writer, ttl_seconds=0)
