"""Minimal worker service that pushes status updates to the shared Redis store."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from pydantic import BaseModel, Field

from task_state import TaskRecord, TaskStatus
from task_state.redis import RedisRepositoryProvider, RedisRepositorySettings

logger = logging.getLogger(__name__)


class WorkloadResult(BaseModel):
    """Simplified result payload published by the worker."""

    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float
    detail: str


@dataclass(slots=True)
class TaskStatusPublisher:
    """High-level helper that wraps Redis operations for the worker."""

    provider: RedisRepositoryProvider

    @asynccontextmanager
    async def repository(self) -> AsyncIterator[RedisRepositoryProvider]:
        try:
            await self.provider.get_repository()
            yield self.provider
        finally:
            await self.provider.close()

    async def publish_start(self, task: TaskRecord) -> None:
        repository = await self.provider.get_repository()
        logger.info("Registering task %s as RUNNING", task.task_id)
        await repository.save(task)
        await repository.set_status(task.task_id, TaskStatus.RUNNING, log_entry="Worker started")

    async def publish_completion(self, task_id: str, result: WorkloadResult) -> None:
        repository = await self.provider.get_repository()
        logger.info("Marking task %s as COMPLETED", task_id)
        await repository.append_log(task_id, f"Result: {result.model_dump_json()}")
        await repository.set_status(task_id, TaskStatus.COMPLETED, log_entry="Worker finished")

    async def publish_failure(self, task_id: str, reason: str) -> None:
        repository = await self.provider.get_repository()
        logger.warning("Marking task %s as FAILED", task_id)
        await repository.set_status(task_id, TaskStatus.FAILED, log_entry=reason)


async def _simulate_work(task_id: str) -> WorkloadResult:
    await asyncio.sleep(0.1)
    return WorkloadResult(duration_seconds=0.1, detail=f"Processed task {task_id}")


async def run_worker(task_id: str, *, service: str, user_id: str) -> None:
    settings = RedisRepositorySettings.from_env()
    provider = RedisRepositoryProvider(settings)
    publisher = TaskStatusPublisher(provider)

    task = TaskRecord(
        task_id=task_id,
        service=service,
        user_id=user_id,
        status=TaskStatus.PENDING,
    )

    try:
        await publisher.publish_start(task)
        result = await _simulate_work(task_id)
        await publisher.publish_completion(task_id, result)
    except Exception as exc:  # pragma: no cover - demonstration only
        await publisher.publish_failure(task_id, f"worker failure: {exc}")
        raise
    finally:
        await provider.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    task_id = "demo"
    asyncio.run(run_worker(task_id, service="example-service", user_id="system"))


if __name__ == "__main__":
    main()
