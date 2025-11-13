from __future__ import annotations

from fastapi import APIRouter

from app.services.models import HelpResponse

router = APIRouter(tags=["meta"])


@router.get("/help", response_model=HelpResponse)
async def help_endpoint() -> HelpResponse:
    return HelpResponse(
        description="Distributed Management Service frontend API",
        endpoints=[
            "GET /api/v1/services/{service}/users/{user_id}/tasks",
            "POST /api/v1/services/{service}/users/{user_id}/tasks",
            "GET /api/v1/services/{service}/tasks/{task_id}?user_id=",
            "GET /api/v1/services/{service}/tasks/{task_id}/logs?user_id=",
            "POST /api/v1/services/{service}/tasks/{task_id}/cancel?user_id=",
            "DELETE /api/v1/services/{service}/tasks/{task_id}?user_id=",
            "GET /api/v1/admin/tasks",
            "GET /api/v1/admin/services/{service}/tasks",
            "POST /api/v1/admin/tasks/{task_id}/cancel",
            "DELETE /api/v1/admin/tasks/{task_id}",
        ],
    )
