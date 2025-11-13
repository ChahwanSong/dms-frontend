from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


class EventType(str, enum.Enum):
    TASK_SUBMITTED = "task_submitted"
    TASK_CANCELLED = "task_cancelled"


@dataclass(slots=True)
class Event:
    type: EventType
    payload: Dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class TaskSubmission(Event):
    type: EventType = EventType.TASK_SUBMITTED


@dataclass(slots=True)
class TaskCancellation(Event):
    type: EventType = EventType.TASK_CANCELLED
