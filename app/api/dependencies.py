from __future__ import annotations

from app.services.tasks import TaskService

from ..services_container import get_task_service_instance


def get_task_service() -> TaskService:
    return get_task_service_instance()
