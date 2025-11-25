"""Data models shared across services that manipulate task state."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer

from .timezone import now


class TaskStatus(str, enum.Enum):
    """Enumeration of lifecycle stages for long-running tasks."""

    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class PriorityLevel(str, enum.Enum):
    high = "high"
    low = "low"


class TaskResult(BaseModel):
    """Structured result payload attached to a task record."""

    pod_status: Optional[str] = None
    launcher_output: Optional[str] = None


class TaskRecord(BaseModel):
    """Serializable representation of a task stored in Redis."""

    task_id: str
    service: str
    user_id: str
    status: TaskStatus
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    logs: List[str] = Field(default_factory=list)
    result: TaskResult = Field(default_factory=TaskResult)
    priority: PriorityLevel = PriorityLevel.low

    @field_serializer("created_at", "updated_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return value.isoformat()
