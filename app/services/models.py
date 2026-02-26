from __future__ import annotations

from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel

from task_state import TaskRecord, TaskStatus


class TaskCreateResult(BaseModel):
    task_id: str
    status: TaskStatus


class TaskListResponse(BaseModel):
    tasks: List[TaskRecord]


class TaskStatusResponse(BaseModel):
    task: TaskRecord


class TaskUserListResponse(BaseModel):
    users: List[str]


class TaskIdCursorResponse(BaseModel):
    next_task_id: str


class TaskBulkActionResponse(BaseModel):
    matched_count: int
    affected_count: int
    task_ids: List[str]


class ServiceTaskStatusSummary(BaseModel):
    service: str
    pending_task_ids: List[str]
    success_task_ids: List[str]
    failed_task_ids: List[str]


class ServiceTaskSummaryResponse(BaseModel):
    summary: ServiceTaskStatusSummary


class HelpResponse(BaseModel):
    endpoints: Iterable[str]
    description: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    redis: "RedisHealth"


class RedisHealth(BaseModel):
    connected: bool
    message: Optional[str] = None
