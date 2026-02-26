from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.services.models import (
    ServiceTaskStatusSummary,
    ServiceTaskSummaryResponse,
    TaskBulkActionResponse,
    TaskIdCursorResponse,
    TaskListResponse,
    TaskStatusResponse,
)
from app.services.tasks import TaskService
from task_state import TaskStatus

from ..dependencies import get_task_service
from ..security import require_operator_token

router = APIRouter(tags=["operator"], prefix="/admin")


@router.get("/tasks", response_model=TaskListResponse)
async def list_all_tasks(
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    tasks = await task_service.list_all_tasks()
    return TaskListResponse(tasks=tasks)


@router.get("/tasks/next-id", response_model=TaskIdCursorResponse)
async def get_next_task_id(
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskIdCursorResponse:
    return TaskIdCursorResponse(next_task_id=await task_service.peek_next_task_id())


@router.get("/services/{service}/tasks", response_model=TaskListResponse)
async def list_service_tasks(
    service: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    tasks = await task_service.list_service_tasks(service)
    return TaskListResponse(tasks=tasks)


@router.post("/services/{service}/tasks/cancel", response_model=TaskBulkActionResponse)
async def cancel_service_tasks(
    service: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskBulkActionResponse:
    tasks = await task_service.list_service_tasks(service)
    affected_count, task_ids = await task_service.cancel_tasks(tasks)
    return TaskBulkActionResponse(matched_count=len(tasks), affected_count=affected_count, task_ids=task_ids)


@router.delete("/services/{service}/tasks", response_model=TaskBulkActionResponse)
async def cleanup_service_tasks(
    service: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskBulkActionResponse:
    tasks = await task_service.list_service_tasks(service)
    affected_count, task_ids = await task_service.cleanup_tasks(tasks)
    return TaskBulkActionResponse(matched_count=len(tasks), affected_count=affected_count, task_ids=task_ids)


@router.get("/services/{service}/tasks/summary", response_model=ServiceTaskSummaryResponse)
async def summarize_service_tasks(
    service: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> ServiceTaskSummaryResponse:
    tasks = await task_service.list_service_tasks(service)
    pending_ids = [task.task_id for task in tasks if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.DISPATCHING, TaskStatus.CANCEL_REQUESTED}]
    success_ids = [task.task_id for task in tasks if task.status == TaskStatus.COMPLETED]
    failed_ids = [task.task_id for task in tasks if task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}]
    return ServiceTaskSummaryResponse(
        summary=ServiceTaskStatusSummary(
            service=service,
            pending_task_ids=pending_ids,
            success_task_ids=success_ids,
            failed_task_ids=failed_ids,
        )
    )












@router.post("/tasks/{task_id}/cancel", response_model=TaskStatusResponse)
async def cancel_task(
    task_id: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskStatusResponse:
    task = await task_service.cancel_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskStatusResponse(task=task)


@router.delete("/tasks/{task_id}", response_model=TaskStatusResponse)
async def cleanup_task(
    task_id: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskStatusResponse:
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await task_service.cleanup_task(task_id)
    return TaskStatusResponse(task=task)
