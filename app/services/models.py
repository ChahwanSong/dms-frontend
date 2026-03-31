from __future__ import annotations

from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel

from task_state import TaskRecord, TaskStatus


class OperatorAuthResponse(BaseModel):
    authenticated: Literal[True]
    role: Literal["operator"]


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
    keyevent_notifications_ok: Optional[bool] = None
    keyevent_notifications_value: Optional[str] = None
    expiration_listener_running: Optional[bool] = None
    expiration_listener_stats: Optional[dict] = None
    reconciler_running: Optional[bool] = None
    reconciler_interval_seconds: Optional[float] = None
    reconciler_total_runs: Optional[int] = None
    reconciler_total_cleaned_members: Optional[int] = None
    reconciler_last_run_at: Optional[str] = None
    reconciler_last_error: Optional[str] = None


class RedisMetricsResponse(BaseModel):
    redis: RedisHealth
