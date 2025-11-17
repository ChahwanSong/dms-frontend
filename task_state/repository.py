"""Task repository implementations that can be reused across projects."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
import inspect
from typing import Awaitable, Iterable, List, TypeVar, cast

from redis.asyncio import Redis

from .models import TaskRecord, TaskStatus


class TaskRepository(abc.ABC):
    """Abstract task repository interface shared by services."""

    @abc.abstractmethod
    async def next_task_id(self) -> str: ...

    @abc.abstractmethod
    async def save(self, task: TaskRecord) -> None: ...

    @abc.abstractmethod
    async def get(self, task_id: str) -> TaskRecord | None: ...

    @abc.abstractmethod
    async def delete(self, task_id: str) -> None: ...

    @abc.abstractmethod
    async def set_status(
        self, task_id: str, status: TaskStatus, *, log_entry: str | None = None
    ) -> TaskRecord | None: ...

    @abc.abstractmethod
    async def append_log(self, task_id: str, message: str) -> TaskRecord | None: ...

    @abc.abstractmethod
    async def list_by_ids(self, ids: Iterable[str]) -> List[TaskRecord]: ...

    @abc.abstractmethod
    async def list_all(self) -> List[TaskRecord]: ...

    @abc.abstractmethod
    async def list_by_service(self, service: str) -> List[TaskRecord]: ...

    @abc.abstractmethod
    async def list_by_service_and_user(self, service: str, user_id: str) -> List[TaskRecord]: ...

    @abc.abstractmethod
    async def list_users_by_service(self, service: str) -> List[str]: ...


_T = TypeVar("_T")


class RedisTaskRepository(TaskRepository):
    """Task repository backed by Redis key value store."""

    def __init__(self, reader: Redis, writer: Redis, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        self._reader = reader
        self._writer = writer
        self._ttl_seconds = int(ttl_seconds)

    async def _execute(self, command: Awaitable[_T] | _T) -> _T:
        if inspect.isawaitable(command):
            return await cast(Awaitable[_T], command)
        return cast(_T, command)

    async def next_task_id(self) -> str:
        next_id = await self._execute(self._writer.incr("task:id:sequence"))
        return str(next_id)

    async def save(self, task: TaskRecord) -> None:
        await self._execute(
            self._writer.set(
                self._task_key(task.task_id),
                task.model_dump_json(),
                ex=self._ttl_seconds,
            )
        )
        await self._execute(self._writer.sadd("index:tasks", task.task_id))
        await self._ensure_ttl("index:tasks")
        service_index = self._service_index(task.service)
        await self._execute(self._writer.sadd(service_index, task.task_id))
        await self._ensure_ttl(service_index)
        service_users_index = self._service_users_index(task.service)
        await self._execute(self._writer.sadd(service_users_index, task.user_id))
        await self._ensure_ttl(service_users_index)
        service_user_index = self._service_user_index(task.service, task.user_id)
        await self._execute(self._writer.sadd(service_user_index, task.task_id))
        await self._ensure_ttl(service_user_index)

    async def get(self, task_id: str) -> TaskRecord | None:
        raw = await self._execute(self._reader.get(self._task_key(task_id)))
        if not raw:
            return None
        return TaskRecord.model_validate_json(raw)

    async def delete(self, task_id: str) -> None:
        task = await self.get(task_id)
        if not task:
            return
        await self._execute(self._writer.delete(self._task_key(task_id)))
        await self._execute(self._writer.srem("index:tasks", task_id))
        await self._execute(self._writer.srem(self._service_index(task.service), task_id))
        await self._execute(
            self._writer.srem(self._service_user_index(task.service, task.user_id), task_id)
        )
        await self._cleanup_user_index(task.service, task.user_id)

    async def set_status(
        self, task_id: str, status: TaskStatus, *, log_entry: str | None = None
    ) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = datetime.now(timezone.utc)
        if log_entry:
            task.logs.append(log_entry)
        await self.save(task)
        return task

    async def append_log(self, task_id: str, message: str) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.logs.append(message)
        task.updated_at = datetime.now(timezone.utc)
        await self.save(task)
        return task

    async def list_by_ids(self, ids: Iterable[str]) -> List[TaskRecord]:
        ids_list = list(ids)
        if not ids_list:
            return []
        raw_values = await self._execute(
            self._reader.mget([self._task_key(task_id) for task_id in ids_list])
        )
        return [TaskRecord.model_validate_json(raw) for raw in raw_values if raw]

    async def list_all(self) -> List[TaskRecord]:
        ids = await self._execute(self._reader.smembers("index:tasks"))
        return await self.list_by_ids(ids)

    async def list_by_service(self, service: str) -> List[TaskRecord]:
        ids = await self._execute(self._reader.smembers(self._service_index(service)))
        return await self.list_by_ids(ids)

    async def list_by_service_and_user(self, service: str, user_id: str) -> List[TaskRecord]:
        ids = await self._execute(
            self._reader.smembers(self._service_user_index(service, user_id))
        )
        return await self.list_by_ids(ids)

    async def list_users_by_service(self, service: str) -> List[str]:
        raw_users = await self._execute(self._reader.smembers(self._service_users_index(service)))
        return [user.decode() if isinstance(user, bytes) else str(user) for user in raw_users]

    @staticmethod
    def _task_key(task_id: str) -> str:
        return f"task:{task_id}"

    @staticmethod
    def _service_index(service: str) -> str:
        return f"index:service:{service}"

    @staticmethod
    def _service_user_index(service: str, user_id: str) -> str:
        return f"index:service:{service}:user:{user_id}"

    @staticmethod
    def _service_users_index(service: str) -> str:
        return f"index:service:{service}:users"

    async def _ensure_ttl(self, key: str) -> None:
        await self._execute(self._writer.expire(key, self._ttl_seconds))

    async def _cleanup_user_index(self, service: str, user_id: str) -> None:
        service_user_index = self._service_user_index(service, user_id)
        remaining = await self._execute(self._reader.scard(service_user_index))
        if remaining:
            await self._ensure_ttl(service_user_index)
            return
        await self._execute(self._writer.srem(self._service_users_index(service), user_id))
        await self._ensure_ttl(self._service_users_index(service))

