"""Redis connection helpers for shared task repository usage."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from .repository import RedisTaskRepository
from .timezone import DEFAULT_TIMEZONE_NAME, _coerce_timezone, set_default_timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RedisRepositorySettings:
    """Configuration required to build a Redis-backed repository."""

    write_url: str
    read_url: str
    ttl_seconds: int
    decode_responses: bool = True
    timezone_name: str = DEFAULT_TIMEZONE_NAME
    keyevent_validation_required: bool = True
    reconcile_interval_seconds: float = 300.0

    @classmethod
    def from_env(
        cls,
        *,
        ttl_seconds: Optional[int] = None,
        write_env: str = "DMS_REDIS_WRITE_URL",
        read_env: str = "DMS_REDIS_READ_URL",
        timezone_env: str = "DMS_TIMEZONE",
    ) -> "RedisRepositorySettings":
        """Load configuration from environment variables.

        Falls back to the write URL when a dedicated read URL is not supplied.
        """

        write_url = os.getenv(write_env)
        if not write_url:
            raise RuntimeError(f"Environment variable {write_env} is required")
        read_url = os.getenv(read_env, write_url)
        if ttl_seconds is None:
            ttl_env = os.getenv("DMS_REDIS_TASK_TTL_SECONDS")
            ttl_seconds = int(ttl_env) if ttl_env else 90 * 24 * 60 * 60
        timezone_name = os.getenv(timezone_env, DEFAULT_TIMEZONE_NAME)
        _coerce_timezone(timezone_name)
        return cls(
            write_url=write_url,
            read_url=read_url,
            ttl_seconds=int(ttl_seconds),
            timezone_name=timezone_name,
        )


class RedisRepositoryProvider:
    """Manage Redis clients and expose a ready-to-use repository instance."""

    def __init__(self, settings: RedisRepositorySettings) -> None:
        self._settings = settings
        self._reader: Optional[Redis] = None
        self._writer: Optional[Redis] = None
        self._repository: Optional[RedisTaskRepository] = None
        self._expiration_listener: Optional[TaskExpirationSubscriber] = None
        self._keyevent_notifications_ok = False
        self._keyevent_notifications_value: Optional[str] = None
        self._reconciler_task: asyncio.Task[None] | None = None
        self._reconciler_running = False
        self._reconciler_last_run_at: Optional[str] = None
        self._reconciler_last_error: Optional[str] = None
        self._reconciler_total_runs = 0
        self._reconciler_total_cleaned_members = 0

    @property
    def reader(self) -> Optional[Redis]:
        return self._reader

    @property
    def writer(self) -> Optional[Redis]:
        return self._writer

    async def get_repository(self) -> RedisTaskRepository:
        """Create (or return) the Redis-backed repository."""

        if self._repository is None:
            set_default_timezone(self._settings.timezone_name)
            writer = Redis.from_url(
                self._settings.write_url, decode_responses=self._settings.decode_responses
            )
            reader = Redis.from_url(
                self._settings.read_url, decode_responses=self._settings.decode_responses
            )
            try:
                await writer.ping()
                await reader.ping()
                await self._validate_keyevent_notifications(writer)
            except Exception:
                await writer.aclose()
                await reader.aclose()
                raise
            self._writer = writer
            self._reader = reader
            self._repository = RedisTaskRepository(
                reader=reader,
                writer=writer,
                ttl_seconds=self._settings.ttl_seconds,
                tzinfo=_coerce_timezone(self._settings.timezone_name),
            )
        return self._repository

    async def start_key_expiration_listener(self) -> None:
        """Start a background consumer for Redis key expiration events."""

        if self._repository is None or self._reader is None:
            await self.get_repository()
        if self._repository is None or self._reader is None:
            return
        if self._expiration_listener is None:
            self._expiration_listener = TaskExpirationSubscriber(
                reader=self._reader, repository=self._repository
            )
        await self._expiration_listener.start()
        await self._start_reconciler_if_needed()

    async def stop_key_expiration_listener(self) -> None:
        if self._reconciler_task:
            self._reconciler_running = False
            self._reconciler_task.cancel()
            await asyncio.gather(self._reconciler_task, return_exceptions=True)
            self._reconciler_task = None
        if self._expiration_listener:
            await self._expiration_listener.stop()
            self._expiration_listener = None

    async def close(self) -> None:
        """Close the Redis clients created by the provider."""

        await self.stop_key_expiration_listener()
        if self._reader:
            await self._reader.aclose()
        if self._writer:
            await self._writer.aclose()
        self._reader = None
        self._writer = None
        self._repository = None

    async def _validate_keyevent_notifications(self, redis_client: Redis) -> None:
        config = await redis_client.config_get("notify-keyspace-events")
        value = str(config.get("notify-keyspace-events", "") or "")
        self._keyevent_notifications_value = value
        has_required_flags = "E" in value and ("x" in value or "A" in value)
        self._keyevent_notifications_ok = has_required_flags
        if self._settings.keyevent_validation_required and not has_required_flags:
            raise RuntimeError(
                "Redis notify-keyspace-events must include 'E' and 'x' "
                f"(or 'A'). Current value: {value!r}"
            )

    async def _start_reconciler_if_needed(self) -> None:
        if self._repository is None or self._reader is None or self._writer is None:
            return
        if self._settings.reconcile_interval_seconds <= 0:
            return
        if self._reconciler_task is not None:
            return
        self._reconciler_running = True
        self._reconciler_task = asyncio.create_task(self._reconcile_loop())

    async def _reconcile_loop(self) -> None:
        while self._reconciler_running:
            try:
                cleaned_members = await self._reconcile_indexes_once()
                self._reconciler_total_cleaned_members += cleaned_members
                self._reconciler_total_runs += 1
                self._reconciler_last_error = None
                self._reconciler_last_run_at = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._reconciler_total_runs += 1
                self._reconciler_last_run_at = datetime.now(timezone.utc).isoformat()
                self._reconciler_last_error = str(exc)
                logger.exception("Redis index reconciler failed")

            await asyncio.sleep(self._settings.reconcile_interval_seconds)

    async def _reconcile_indexes_once(self) -> int:
        if self._reader is None or self._writer is None:
            return 0
        cleaned = 0
        async for key in self._reader.scan_iter(match="index:*"):
            index_key = key.decode() if isinstance(key, bytes) else str(key)
            async for member in self._reader.sscan_iter(index_key):
                task_id = member.decode() if isinstance(member, bytes) else str(member)
                task_exists = await self._reader.exists(f"task:{task_id}")
                if task_exists:
                    continue
                cleaned += await self._writer.srem(index_key, task_id)
        return cleaned

    def get_runtime_status(self) -> dict:
        listener_stats = (
            self._expiration_listener.snapshot()
            if self._expiration_listener
            else TaskExpirationSubscriberStats().to_dict()
        )
        return {
            "keyevent_notifications_ok": self._keyevent_notifications_ok,
            "keyevent_notifications_value": self._keyevent_notifications_value,
            "expiration_listener_running": self._expiration_listener is not None,
            "expiration_listener_stats": listener_stats,
            "reconciler_running": self._reconciler_task is not None,
            "reconciler_interval_seconds": self._settings.reconcile_interval_seconds,
            "reconciler_total_runs": self._reconciler_total_runs,
            "reconciler_total_cleaned_members": self._reconciler_total_cleaned_members,
            "reconciler_last_run_at": self._reconciler_last_run_at,
            "reconciler_last_error": self._reconciler_last_error,
        }


@dataclass(slots=True)
class TaskExpirationSubscriberStats:
    total_messages: int = 0
    task_messages: int = 0
    cleanup_successes: int = 0
    metadata_missing: int = 0
    cleanup_failures: int = 0
    last_error: Optional[str] = None
    last_message_at: Optional[str] = None
    reconnect_count: int = 0

    def to_dict(self) -> dict:
        return {
            "total_messages": self.total_messages,
            "task_messages": self.task_messages,
            "cleanup_successes": self.cleanup_successes,
            "metadata_missing": self.metadata_missing,
            "cleanup_failures": self.cleanup_failures,
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
            "reconnect_count": self.reconnect_count,
        }


class TaskExpirationSubscriber:
    """Background task that reacts to Redis key expiration events."""

    def __init__(self, *, reader: Redis, repository: RedisTaskRepository) -> None:
        self._reader = reader
        self._repository = repository
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._pubsub = None
        self._db_index = self._reader.connection_pool.connection_kwargs.get("db", 0)
        self._stats = TaskExpirationSubscriberStats()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        if self._pubsub:
            await self._pubsub.aclose()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._pubsub = None

    async def _run(self) -> None:
        channel = f"__keyevent@{self._db_index}__:expired"
        while not self._stopped.is_set():
            try:
                async with self._reader.pubsub() as pubsub:
                    self._pubsub = pubsub
                    await pubsub.psubscribe(channel)
                    logger.info("Subscribed to Redis expiration events on %s", channel)

                    while not self._stopped.is_set():
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=1.0,
                        )
                        if not message:
                            continue
                        await self._handle_message(message)

            except asyncio.CancelledError:
                # 종료 시에는 그대로 빠져나감
                raise

            except RedisConnectionError as exc:
                if self._stopped.is_set():
                    # 이미 stop 요청이 들어간 상태라면 그냥 조용히 종료
                    break

                logger.warning(
                    "Redis connection closed while listening for expirations: %s. "
                    "Will retry in 5 seconds.",
                    exc,
                )
                self._stats.reconnect_count += 1
                await asyncio.sleep(5)

            except Exception:
                logger.exception("Failed to process Redis expiration notifications")
                self._stats.last_error = "Failed to process Redis expiration notifications"
                # 너무 시끄럽다면 여기서도 retry 하고 싶을 수 있음
                await asyncio.sleep(5)

        logger.info("TaskExpirationSubscriber stopped")

    async def _handle_message(self, message: dict) -> None:
        self._stats.total_messages += 1
        self._stats.last_message_at = datetime.now(timezone.utc).isoformat()
        key = message.get("data")
        if isinstance(key, bytes):
            key = key.decode()
        if not isinstance(key, str):
            return
        if not key.startswith("task:"):
            return
        self._stats.task_messages += 1
        task_id = key.removeprefix("task:")
        try:
            cleaned = await self._repository.handle_task_expired(task_id)
        except Exception as exc:
            self._stats.cleanup_failures += 1
            self._stats.last_error = str(exc)
            raise
        if cleaned:
            self._stats.cleanup_successes += 1
        else:
            self._stats.metadata_missing += 1

    def snapshot(self) -> dict:
        return self._stats.to_dict()
