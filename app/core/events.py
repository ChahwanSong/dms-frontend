from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Dict

from task_state.timezone import now


class EventType(str, enum.Enum):
    TASK_SUBMITTED = "task_submitted"
    TASK_CANCELLED = "task_cancelled"


@dataclass(slots=True)
class Event:
    type: ClassVar[EventType]
    payload: Dict[str, Any]
    created_at: datetime = field(default_factory=now)


@dataclass(slots=True)
class TaskSubmission(Event):
    type: ClassVar[EventType] = EventType.TASK_SUBMITTED


@dataclass(slots=True)
class TaskCancellation(Event):
    type: ClassVar[EventType] = EventType.TASK_CANCELLED
