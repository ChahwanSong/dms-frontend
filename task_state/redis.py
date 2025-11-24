"""Redis connection helpers for shared task repository usage."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
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

    async def stop_key_expiration_listener(self) -> None:
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


class TaskExpirationSubscriber:
    """Background task that reacts to Redis key expiration events."""

    def __init__(self, *, reader: Redis, repository: RedisTaskRepository) -> None:
        self._reader = reader
        self._repository = repository
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._pubsub = None
        self._db_index = self._reader.connection_pool.connection_kwargs.get("db", 0)

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
                await asyncio.sleep(5)

            except Exception:
                logger.exception("Failed to process Redis expiration notifications")
                # 너무 시끄럽다면 여기서도 retry 하고 싶을 수 있음
                await asyncio.sleep(5)

        logger.info("TaskExpirationSubscriber stopped")

    async def _handle_message(self, message: dict) -> None:
        key = message.get("data")
        if isinstance(key, bytes):
            key = key.decode()
        if not isinstance(key, str):
            return
        if not key.startswith("task:"):
            return
        task_id = key.removeprefix("task:")
        await self._repository.handle_task_expired(task_id)
