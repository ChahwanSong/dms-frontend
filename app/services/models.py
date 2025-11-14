from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, field_serializer


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class TaskRecord(BaseModel):
    task_id: str
    service: str
    user_id: str
    status: TaskStatus
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logs: List[str] = Field(default_factory=list)

    @field_serializer("created_at", "updated_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return value.isoformat()


class TaskCreateResult(BaseModel):
    task_id: str
    status: TaskStatus


class TaskListResponse(BaseModel):
    tasks: List[TaskRecord]


class TaskStatusResponse(BaseModel):
    task: TaskRecord


class HelpResponse(BaseModel):
    endpoints: Iterable[str]
    description: Optional[str] = None
