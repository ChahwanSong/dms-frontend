from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.event_processor import TaskEventProcessor
from app.services.repository import InMemoryTaskRepository, RedisTaskRepository, TaskRepository
from app.services.scheduler import SchedulerClient
from app.services.tasks import TaskService

logger = logging.getLogger(__name__)

_settings: Optional[Settings] = None
_task_service: Optional[TaskService] = None
_event_processor: Optional[TaskEventProcessor] = None
_scheduler_client: Optional[SchedulerClient] = None
_redis_reader: Optional[Redis] = None
_redis_writer: Optional[Redis] = None


async def init_services(
    settings: Optional[Settings] = None,
    repository: Optional[TaskRepository] = None,
    scheduler: Optional[SchedulerClient] = None,
) -> None:
    global _settings, _task_service, _event_processor, _scheduler_client, _redis_reader, _redis_writer

    _settings = settings or get_settings()
    configure_logging(_settings)

    if repository is None:
        if _settings.use_in_memory_store:
            repository = InMemoryTaskRepository()
            _redis_reader = None
            _redis_writer = None
        else:
            _redis_writer = Redis.from_url(_settings.redis_write_url, decode_responses=True)
            _redis_reader = Redis.from_url(_settings.redis_read_url, decode_responses=True)
            try:
                await _redis_writer.ping()
                await _redis_reader.ping()
            except Exception:
                logger.exception("Failed to connect to Redis during startup")
                raise
            else:
                logger.info("Successfully connected to Redis for read/write operations")
            repository = RedisTaskRepository(
                reader=_redis_reader,
                writer=_redis_writer,
                ttl_seconds=_settings.redis_task_ttl_seconds,
            )
    else:
        _redis_reader = None
        _redis_writer = None

    _scheduler_client = scheduler or SchedulerClient(_settings)
    _event_processor = TaskEventProcessor(repository, _scheduler_client, worker_count=_settings.event_worker_count)
    _task_service = TaskService(repository, _event_processor)
    await _event_processor.start()


async def shutdown_services() -> None:
    global _task_service, _event_processor, _scheduler_client, _redis_reader, _redis_writer

    if _event_processor:
        await _event_processor.stop()
    if _scheduler_client:
        await _scheduler_client.aclose()
    if _redis_reader:
        await _redis_reader.aclose()
    if _redis_writer:
        await _redis_writer.aclose()
    _task_service = None
    _event_processor = None
    _scheduler_client = None
    _redis_reader = None
    _redis_writer = None


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
