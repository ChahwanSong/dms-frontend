from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.services.models import (
    TaskCreateResult,
    TaskListResponse,
    TaskStatusResponse,
    TaskUserListResponse,
)
from app.services.tasks import TaskService

from ..dependencies import get_task_service
from ..security import require_operator_token

router = APIRouter(tags=["user"], prefix="/services", dependencies=[Depends(require_operator_token)])


@router.get("/{service}/users", response_model=TaskUserListResponse)
async def list_service_users(service: str, task_service: TaskService = Depends(get_task_service)) -> TaskUserListResponse:
    users = await task_service.list_service_users(service)
    return TaskUserListResponse(users=users)


@router.get("/{service}/users/{user_id}/tasks", response_model=TaskListResponse)
async def list_user_tasks(service: str, user_id: str, task_service: TaskService = Depends(get_task_service)) -> TaskListResponse:
    tasks = await task_service.list_user_tasks(service, user_id)
    return TaskListResponse(tasks=tasks)


@router.post("/{service}/users/{user_id}/tasks", response_model=TaskCreateResult, status_code=status.HTTP_202_ACCEPTED)
async def create_task(service: str, user_id: str, request: Request, task_service: TaskService = Depends(get_task_service)) -> TaskCreateResult:
    parameters: dict[str, Any] = dict(request.query_params)
    result = await task_service.create_task(service, user_id, parameters)
    return result


@router.get("/{service}/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(service: str, task_id: str, user_id: str = Query(...), task_service: TaskService = Depends(get_task_service)) -> TaskStatusResponse:
    task = await task_service.get_task(task_id)
    if not task or task.service != service or task.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskStatusResponse(task=task)


@router.post("/{service}/tasks/{task_id}/cancel", response_model=TaskStatusResponse)
async def cancel_task(service: str, task_id: str, user_id: str = Query(...), task_service: TaskService = Depends(get_task_service)) -> TaskStatusResponse:
    task = await task_service.cancel_task(task_id, service=service, user_id=user_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskStatusResponse(task=task)


@router.delete("/{service}/tasks/{task_id}", response_model=TaskStatusResponse)
async def cleanup_task(service: str, task_id: str, user_id: str = Query(...), task_service: TaskService = Depends(get_task_service)) -> TaskStatusResponse:
    task = await task_service.get_task(task_id)
    if not task or task.service != service or task.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await task_service.cleanup_task(task_id, service=service, user_id=user_id)
    return TaskStatusResponse(task=task)
