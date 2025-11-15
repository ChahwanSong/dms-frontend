from __future__ import annotations

import abc
from datetime import datetime, timezone
import inspect
from typing import Awaitable, Iterable, List, TypeVar, cast

from redis.asyncio import Redis

from .models import TaskRecord, TaskStatus


class TaskRepository(abc.ABC):
    """Abstract task repository."""

    @abc.abstractmethod
    async def next_task_id(self) -> str: ...

    @abc.abstractmethod
    async def save(self, task: TaskRecord) -> None: ...

    @abc.abstractmethod
    async def get(self, task_id: str) -> TaskRecord | None: ...

    @abc.abstractmethod
    async def delete(self, task_id: str) -> None: ...

    @abc.abstractmethod
    async def set_status(self, task_id: str, status: TaskStatus, *, log_entry: str | None = None) -> TaskRecord | None: ...

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


_T = TypeVar("_T")


class RedisTaskRepository(TaskRepository):
    """Task repository backed by Redis key value store."""

    def __init__(self, reader: Redis, writer: Redis) -> None:
        self._reader = reader
        self._writer = writer

    async def _execute(self, command: Awaitable[_T] | _T) -> _T:
        if inspect.isawaitable(command):
            return await cast(Awaitable[_T], command)
        return cast(_T, command)

    async def next_task_id(self) -> str:
        next_id = await self._execute(self._writer.incr("task:id:sequence"))
        return str(next_id)

    async def save(self, task: TaskRecord) -> None:
        await self._execute(self._writer.set(self._task_key(task.task_id), task.model_dump_json()))
        await self._execute(self._writer.sadd("index:tasks", task.task_id))
        await self._execute(self._writer.sadd(self._service_index(task.service), task.task_id))
        await self._execute(self._writer.sadd(self._service_user_index(task.service, task.user_id), task.task_id))

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
        await self._execute(self._writer.srem(self._service_user_index(task.service, task.user_id), task_id))

    async def set_status(self, task_id: str, status: TaskStatus, *, log_entry: str | None = None) -> TaskRecord | None:
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
        ids = await self._execute(self._reader.smembers(self._service_user_index(service, user_id)))
        return await self.list_by_ids(ids)

    @staticmethod
    def _task_key(task_id: str) -> str:
        return f"task:{task_id}"

    @staticmethod
    def _service_index(service: str) -> str:
        return f"index:service:{service}"

    @staticmethod
    def _service_user_index(service: str, user_id: str) -> str:
        return f"index:service:{service}:user:{user_id}"


class InMemoryTaskRepository(TaskRepository):
    """In-memory repository used for testing."""

    def __init__(self) -> None:
        self._store: dict[str, TaskRecord] = {}
        self._service_index: dict[str, set[str]] = {}
        self._service_user_index: dict[tuple[str, str], set[str]] = {}
        self._sequence = 0

    async def next_task_id(self) -> str:
        self._sequence += 1
        return str(self._sequence)

    async def save(self, task: TaskRecord) -> None:
        self._store[task.task_id] = task
        self._service_index.setdefault(task.service, set()).add(task.task_id)
        self._service_user_index.setdefault((task.service, task.user_id), set()).add(task.task_id)

    async def get(self, task_id: str) -> TaskRecord | None:
        return self._store.get(task_id)

    async def delete(self, task_id: str) -> None:
        task = self._store.pop(task_id, None)
        if not task:
            return
        self._service_index.get(task.service, set()).discard(task_id)
        self._service_user_index.get((task.service, task.user_id), set()).discard(task_id)

    async def set_status(self, task_id: str, status: TaskStatus, *, log_entry: str | None = None) -> TaskRecord | None:
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
        return [self._store[task_id] for task_id in ids if task_id in self._store]

    async def list_all(self) -> List[TaskRecord]:
        return list(self._store.values())

    async def list_by_service(self, service: str) -> List[TaskRecord]:
        ids = self._service_index.get(service, set())
        return await self.list_by_ids(ids)

    async def list_by_service_and_user(self, service: str, user_id: str) -> List[TaskRecord]:
        ids = self._service_user_index.get((service, user_id), set())
        return await self.list_by_ids(ids)
