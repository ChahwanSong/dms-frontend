from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from app.core.config import get_settings
from app.main import create_app


class StubSchedulerClient:
    def __init__(self, settings) -> None:
        self.submissions: list[dict] = []
        self.cancellations: list[dict] = []

    async def submit_task(self, payload: dict) -> None:
        self.submissions.append(payload)

    async def cancel_task(self, payload: dict) -> None:
        self.cancellations.append(payload)

    async def aclose(self) -> None:
        return None


@pytest.fixture
async def test_app(monkeypatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DMS_USE_IN_MEMORY_STORE", "true")
    monkeypatch.setenv("DMS_OPERATOR_TOKEN", "secret")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    from app import services_container

    monkeypatch.setattr(services_container, "SchedulerClient", StubSchedulerClient)

    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def wait_for_condition(condition, timeout: float = 1.0) -> None:
    start = asyncio.get_event_loop().time()
    while True:
        if await condition():
            return
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError("Condition not met within timeout")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_user_can_create_and_list_tasks(test_app: AsyncClient) -> None:
    create_response = await test_app.post("/api/v1/services/sync/users/alice/tasks", params={"input": "value"})
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    async def _task_running() -> bool:
        response = await test_app.get(f"/api/v1/services/sync/tasks/{task_id}", params={"user_id": "alice"})
        return response.status_code == 200 and response.json()["task"]["status"] in {"running", "completed"}

    await wait_for_condition(_task_running)

    list_response = await test_app.get("/api/v1/services/sync/users/alice/tasks")
    assert list_response.status_code == 200
    tasks = list_response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task_id


@pytest.mark.asyncio
async def test_operator_token_required(test_app: AsyncClient) -> None:
    response = await test_app.get("/api/v1/admin/tasks", headers={"X-Operator-Token": "wrong"})
    assert response.status_code == 401

    response = await test_app.get("/api/v1/admin/tasks", headers={"X-Operator-Token": "secret"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_can_cancel_task(test_app: AsyncClient) -> None:
    create_response = await test_app.post("/api/v1/services/scan/users/bob/tasks")
    task_id = create_response.json()["task_id"]

    cancel_response = await test_app.post(f"/api/v1/services/scan/tasks/{task_id}/cancel", params={"user_id": "bob"})
    assert cancel_response.status_code == 200

    async def _task_cancelled() -> bool:
        response = await test_app.get(f"/api/v1/services/scan/tasks/{task_id}", params={"user_id": "bob"})
        return response.status_code == 200 and response.json()["task"]["status"] == "cancelled"

    await wait_for_condition(_task_cancelled)
