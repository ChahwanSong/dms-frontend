from __future__ import annotations

import asyncio
import logging
from starlette import status

from app.core.events import Event, EventType

from .models import TaskStatus
from .repository import TaskRepository
from .scheduler import (
    SchedulerClient,
    SchedulerResponseError,
    SchedulerUnavailableError,
)

logger = logging.getLogger(__name__)


class TaskEventProcessor:
    """Async event processor that fans out work to the scheduler."""

    def __init__(self, repository: TaskRepository, scheduler: SchedulerClient, *, worker_count: int = 4) -> None:
        self._repository = repository
        self._scheduler = scheduler
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._worker_count = max(1, worker_count)
        self._workers: list[asyncio.Task[None]] = []
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        logger.info("Starting event processor", extra={"workers": self._worker_count})
        self._stopped.clear()
        for _ in range(self._worker_count):
            worker = asyncio.create_task(self._run_worker())
            self._workers.append(worker)

    async def stop(self) -> None:
        logger.info("Stopping event processor")
        self._stopped.set()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def publish(self, event: Event) -> None:
        logger.debug("Queueing event", extra={"type": event.type})
        await self._queue.put(event)

    async def _run_worker(self) -> None:
        while not self._stopped.is_set():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._handle_event(event)
            except Exception:  # pragma: no cover - safeguard
                logger.exception("Failed to handle event", extra={"event_type": event.type})
            finally:
                self._queue.task_done()

    async def _handle_event(self, event: Event) -> None:
        if event.type is EventType.TASK_SUBMITTED:
            await self._handle_task_submission(event)
        elif event.type is EventType.TASK_CANCELLED:
            await self._handle_task_cancellation(event)
        else:  # pragma: no cover - defensive
            logger.warning("Unknown event type", extra={"event_type": event.type})

    async def _handle_task_submission(self, event: Event) -> None:
        task_id = event.payload["task_id"]
        service = event.payload["service"]
        user_id = event.payload["user_id"]
        parameters = event.payload.get("parameters", {})
        try:
            await self._repository.set_status(task_id, TaskStatus.DISPATCHING, log_entry="Dispatching to scheduler")
            await self._scheduler.submit_task({
                "task_id": task_id,
                "service": service,
                "user_id": user_id,
                "parameters": parameters,
            })
            await self._repository.append_log(task_id, "Scheduler acknowledged submission")
        except SchedulerUnavailableError as exc:  # pragma: no cover - network failure path
            logger.error(
                "Task submission failed - scheduler unavailable",
                extra={"task_id": task_id, "scheduler_url": exc.url},
            )
            await self._repository.set_status(
                task_id,
                TaskStatus.FAILED,
                log_entry=f"Scheduler unavailable at {exc.url}: {exc.original}",
            )
        except SchedulerResponseError as exc:
            logger.error(
                "Task submission failed - scheduler returned error",
                extra={
                    "task_id": task_id,
                    "scheduler_url": exc.url,
                    "status_code": exc.status_code,
                    "response": exc.response_text,
                },
            )
            if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                await self._repository.set_status(
                    task_id,
                    TaskStatus.FAILED,
                    log_entry=f"Scheduler returned {exc.status_code}: {exc.response_text}",
                )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Task submission failed", extra={"task_id": task_id})
            await self._repository.set_status(task_id, TaskStatus.FAILED, log_entry=str(exc))
        else:
            await self._repository.set_status(task_id, TaskStatus.RUNNING)

    async def _handle_task_cancellation(self, event: Event) -> None:
        task_id = event.payload["task_id"]
        service = event.payload["service"]
        user_id = event.payload.get("user_id")
        failure_status: TaskStatus | None = None
        failure_log: str | None = None
        try:
            await self._scheduler.cancel_task({
                "task_id": task_id,
                "service": service,
                "user_id": user_id,
            })
        except SchedulerResponseError as exc:
            logger.error(
                "Task cancellation failed - scheduler returned error",
                extra={
                    "task_id": task_id,
                    "scheduler_url": exc.url,
                    "status_code": exc.status_code,
                    "response": exc.response_text,
                },
            )
            if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                failure_status = TaskStatus.FAILED
                failure_log = f"Scheduler returned {exc.status_code}: {exc.response_text}"
        except SchedulerUnavailableError as exc:  # pragma: no cover - network failure path
            logger.error(
                "Task cancellation failed - scheduler unavailable",
                extra={"task_id": task_id, "scheduler_url": exc.url},
            )
            await self._repository.append_log(
                task_id, f"Scheduler unavailable at {exc.url}: {exc.original}"
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Task cancellation failed", extra={"task_id": task_id})
            await self._repository.append_log(task_id, f"Cancellation error: {exc}")
        if failure_status is TaskStatus.FAILED:
            await self._repository.set_status(task_id, failure_status, log_entry=failure_log)
        else:
            await self._repository.set_status(task_id, TaskStatus.CANCELLED, log_entry="Task cancelled")
