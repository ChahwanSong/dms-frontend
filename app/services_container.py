from __future__ import annotations

import logging
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.event_processor import TaskEventProcessor
from app.services.repository import TaskRepository
from app.services.scheduler import SchedulerClient
from app.services.tasks import TaskService
from task_state.redis import RedisRepositoryProvider, RedisRepositorySettings
from task_state.timezone import set_default_timezone

logger = logging.getLogger(__name__)

_settings: Optional[Settings] = None
_task_service: Optional[TaskService] = None
_event_processor: Optional[TaskEventProcessor] = None
_scheduler_client: Optional[SchedulerClient] = None
_redis_provider: Optional[RedisRepositoryProvider] = None


async def init_services(
    settings: Optional[Settings] = None,
    repository: Optional[TaskRepository] = None,
    scheduler: Optional[SchedulerClient] = None,
) -> None:
    global _settings, _task_service, _event_processor, _scheduler_client, _redis_provider

    _settings = settings or get_settings()
    set_default_timezone(_settings.timezone)
    configure_logging(_settings)

    if repository is None:
        _redis_provider = RedisRepositoryProvider(
            RedisRepositorySettings(
                write_url=_settings.redis_write_url,
                read_url=_settings.redis_read_url,
                ttl_seconds=_settings.redis_task_ttl_seconds,
                timezone_name=_settings.timezone,
            )
        )
        try:
            repository = await _redis_provider.get_repository()
        except Exception:
            logger.exception("Failed to connect to Redis during startup")
            _redis_provider = None
            raise
        else:
            logger.info("Successfully connected to Redis for read/write operations")
    else:
        _redis_provider = None

    _scheduler_client = scheduler or SchedulerClient(_settings)
    _event_processor = TaskEventProcessor(repository, _scheduler_client, worker_count=_settings.event_worker_count)
    _task_service = TaskService(repository, _event_processor)
    await _event_processor.start()


async def shutdown_services() -> None:
    global _task_service, _event_processor, _scheduler_client, _redis_provider

    if _event_processor:
        await _event_processor.stop()
    if _scheduler_client:
        await _scheduler_client.aclose()
    if _redis_provider:
        await _redis_provider.close()
    _task_service = None
    _event_processor = None
    _scheduler_client = None
    _redis_provider = None


def get_task_service_instance() -> TaskService:
    if not _task_service:
        raise RuntimeError("Task service not initialised")
    return _task_service


def override_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def get_settings_instance() -> Settings:
    if not _settings:
        raise RuntimeError("Settings not initialised")
    return _settings
