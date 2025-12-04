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


class HelpResponse(BaseModel):
    endpoints: Iterable[str]
    description: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    redis: "RedisHealth"


class RedisHealth(BaseModel):
    connected: bool
    message: Optional[str] = None
