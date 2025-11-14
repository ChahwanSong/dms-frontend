from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.events import TaskCancellation, TaskSubmission

from .event_processor import TaskEventProcessor
from .models import TaskCreateResult, TaskRecord, TaskStatus
from .repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    """Application service orchestrating task lifecycle operations."""

    def __init__(self, repository: TaskRepository, events: TaskEventProcessor) -> None:
        self._repository = repository
        self._events = events

    async def create_task(self, service: str, user_id: str, parameters: Dict[str, Any]) -> TaskCreateResult:
        task_id = await self._repository.next_task_id()
        record = TaskRecord(
            task_id=task_id,
            service=service,
            user_id=user_id,
            status=TaskStatus.PENDING,
            parameters=parameters,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await self._repository.save(record)
        await self._events.publish(TaskSubmission(payload={
            "task_id": task_id,
            "service": service,
            "user_id": user_id,
            "parameters": parameters,
        }))
        logger.info("Task created", extra={"task_id": task_id, "service": service, "user_id": user_id})
        return TaskCreateResult(task_id=task_id, status=record.status)

    async def list_user_tasks(self, service: str, user_id: str) -> list[TaskRecord]:
        return await self._repository.list_by_service_and_user(service, user_id)

    async def list_service_tasks(self, service: str) -> list[TaskRecord]:
        return await self._repository.list_by_service(service)

    async def list_all_tasks(self) -> list[TaskRecord]:
        return await self._repository.list_all()

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return await self._repository.get(task_id)

    async def cancel_task(
        self,
        task_id: str,
        *,
        service: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> TaskRecord | None:
        record = await self._repository.get(task_id)
        if not record:
            return None
        if service and record.service != service:
            return None
        if user_id and record.user_id != user_id:
            return None

        if record.status in {TaskStatus.CANCELLED, TaskStatus.COMPLETED, TaskStatus.FAILED}:
            return record

        if record.status is not TaskStatus.CANCEL_REQUESTED:
            record = await self._repository.set_status(
                task_id,
                TaskStatus.CANCEL_REQUESTED,
                log_entry="Cancellation requested",
            )
            if not record:  # pragma: no cover - defensive, repository guarantees record exists
                return None

        await self._events.publish(
            TaskCancellation(
                payload={
                    "task_id": task_id,
                    "service": record.service,
                    "user_id": record.user_id,
                }
            )
        )
        return record

    async def cleanup_task(self, task_id: str, *, service: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        record = await self.cancel_task(task_id, service=service, user_id=user_id)
        if not record:
            return False
        await self._repository.delete(task_id)
        return True

    async def append_log(self, task_id: str, message: str) -> TaskRecord | None:
        return await self._repository.append_log(task_id, message)

    async def update_status(self, task_id: str, status: TaskStatus, *, log_entry: str | None = None) -> TaskRecord | None:
        return await self._repository.set_status(task_id, status, log_entry=log_entry)
