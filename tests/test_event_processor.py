from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import pytest

from app.core.events import TaskSubmission
from app.services.event_processor import TaskEventProcessor
from app.services.repository import TaskRepository, format_log_entry
from app.services.scheduler import SchedulerResponseError
from task_state.models import TaskRecord, TaskStatus
from task_state.timezone import now


class _FakeRepository(TaskRepository):
    def __init__(self) -> None:
        self._store: dict[str, TaskRecord] = {}
        self._service_index: defaultdict[str, set[str]] = defaultdict(set)
        self._service_user_index: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        self._service_users: defaultdict[str, set[str]] = defaultdict(set)
        self._sequence = 0

    async def next_task_id(self) -> str:
        self._sequence += 1
        return str(self._sequence)

    async def save(self, task: TaskRecord) -> None:
        self._store[task.task_id] = task
        self._service_index[task.service].add(task.task_id)
        self._service_user_index[(task.service, task.user_id)].add(task.task_id)
        self._service_users[task.service].add(task.user_id)

    async def get(self, task_id: str) -> TaskRecord | None:
        return self._store.get(task_id)

    async def delete(self, task_id: str) -> None:
        task = self._store.pop(task_id, None)
        if not task:
            return
        self._service_index[task.service].discard(task_id)
        self._service_user_index[(task.service, task.user_id)].discard(task_id)
        if not self._service_user_index[(task.service, task.user_id)]:
            self._service_users[task.service].discard(task.user_id)

    async def set_status(
        self, task_id: str, status: TaskStatus, *, log_entry: str | None = None
    ) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = now()
        if log_entry:
            task.logs.append(format_log_entry(log_entry))
        await self.save(task)
        return task

    async def append_log(self, task_id: str, message: str) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.logs.append(format_log_entry(message))
        task.updated_at = now()
        await self.save(task)
        return task

    async def update_result(
        self,
        task_id: str,
        *,
        pod_status: str | None = None,
        launcher_output: str | None = None,
    ) -> TaskRecord | None:
        return await self.get(task_id)

    async def list_by_ids(self, ids: Iterable[str]) -> list[TaskRecord]:
        return [self._store[task_id] for task_id in ids if task_id in self._store]

    async def list_all(self) -> list[TaskRecord]:
        return list(self._store.values())

    async def list_by_service(self, service: str) -> list[TaskRecord]:
        return [self._store[task_id] for task_id in self._service_index.get(service, set())]

    async def list_by_service_and_user(self, service: str, user_id: str) -> list[TaskRecord]:
        key = (service, user_id)
        return [self._store[task_id] for task_id in self._service_user_index.get(key, set())]

    async def list_users_by_service(self, service: str) -> list[str]:
        return list(self._service_users.get(service, set()))


class _ErroringScheduler:
    def __init__(self, *, status_code: int = 400, response_text: str = "") -> None:
        self.payloads: list[dict] = []
        self.status_code = status_code
        self.response_text = response_text or ""

    async def submit_task(self, payload: dict) -> None:
        self.payloads.append(payload)
        raise SchedulerResponseError(
            f"Scheduler responded with {self.status_code}: {self.response_text}",
            url="http://scheduler",
            status_code=self.status_code,
            response_text=self.response_text,
            original=RuntimeError("scheduler error"),
        )

    async def cancel_task(self, payload: dict) -> None:  # pragma: no cover - unused
        self.payloads.append(payload)

    async def aclose(self) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_scheduler_error_logged_without_state_change() -> None:
    repository = _FakeRepository()
    error_message = "{\"detail\":\"Invalid directory\"}"
    scheduler = _ErroringScheduler(response_text=error_message)
    processor = TaskEventProcessor(repository, scheduler, worker_count=1)

    task = TaskRecord(
        task_id="1",
        service="sync",
        user_id="alice",
        status=TaskStatus.PENDING,
        parameters={},
    )
    await repository.save(task)

    event = TaskSubmission(
        payload={
            "task_id": task.task_id,
            "service": task.service,
            "user_id": task.user_id,
            "parameters": task.parameters,
        }
    )

    await processor._handle_task_submission(event)

    updated_task = await repository.get(task.task_id)
    assert updated_task is not None
    assert updated_task.status is TaskStatus.DISPATCHING
    assert len(updated_task.logs) == 1
    assert updated_task.logs[0].endswith(",Dispatching to scheduler")
    assert scheduler.payloads == [
        {
            "task_id": task.task_id,
            "service": task.service,
            "user_id": task.user_id,
            "parameters": task.parameters,
        }
    ]
