from __future__ import annotations

from fastapi import APIRouter

from app.services.models import HealthResponse, HelpResponse

router = APIRouter(tags=["meta"])


@router.get("/help", response_model=HelpResponse)
async def help_endpoint() -> HelpResponse:
    return HelpResponse(
        description="Data Moving Service frontend API",
        endpoints=[
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


@router.get("/healthz", response_model=HealthResponse)
async def health_endpoint() -> HealthResponse:
    return HealthResponse(status="ok")
