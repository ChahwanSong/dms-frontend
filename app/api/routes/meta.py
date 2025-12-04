from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app import services_container
from app.services.models import HealthResponse, HelpResponse, RedisHealth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])
health_router = APIRouter(tags=["meta"])


@router.get("/help", response_model=HelpResponse)
async def help_endpoint() -> HelpResponse:
    return HelpResponse(
        description="Data Moving Service frontend API (X-Operator-Token required for all endpoints except /help and /healthz)",
        endpoints=[
            "GET /healthz",
            "GET /api/v1/services/{service}/users/{user_id}/tasks",
            "POST /api/v1/services/{service}/users/{user_id}/tasks",
            "GET /api/v1/services/{service}/users",
            "GET /api/v1/services/{service}/tasks/{task_id}?user_id=",
            "POST /api/v1/services/{service}/tasks/{task_id}/cancel?user_id=",
            "DELETE /api/v1/services/{service}/tasks/{task_id}?user_id=",
            "GET /api/v1/admin/tasks",
            "GET /api/v1/admin/services/{service}/tasks",
            "POST /api/v1/admin/tasks/{task_id}/cancel",
            "DELETE /api/v1/admin/tasks/{task_id}",
        ],
    )


async def _check_redis_health() -> RedisHealth:
    provider = services_container.get_redis_provider_instance()
    if provider is None:
        logger.error("Redis provider unavailable during health check")
        return RedisHealth(connected=False, message="Redis provider unavailable")

    try:
        await provider.get_repository()
        if provider.writer:
            await provider.writer.ping()
        if provider.reader and provider.reader is not provider.writer:
            await provider.reader.ping()
    except Exception as exc:  # pragma: no cover - defensive logging for observability
        logger.exception("Redis health check failed")
        return RedisHealth(connected=False, message=str(exc))

    return RedisHealth(connected=True)


@health_router.get("/healthz", response_model=HealthResponse, response_model_exclude_none=True)
async def health_endpoint() -> HealthResponse:
    redis_health = await _check_redis_health()
    health = HealthResponse(status="ok" if redis_health.connected else "error", redis=redis_health)
    if not redis_health.connected:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=health.model_dump(exclude_none=True))
    return health
