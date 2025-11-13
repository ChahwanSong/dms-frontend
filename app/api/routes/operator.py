from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.services.models import TaskListResponse, TaskStatusResponse
from app.services.tasks import TaskService

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


@router.get("/services/{service}/tasks", response_model=TaskListResponse)
async def list_service_tasks(
    service: str,
    token: str = Depends(require_operator_token),
    task_service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    tasks = await task_service.list_service_tasks(service)
    return TaskListResponse(tasks=tasks)


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
