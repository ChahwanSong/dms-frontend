from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app
from app.services.models import TaskRecord, TaskStatus
from app.services.repository import TaskRepository, format_log_entry
from task_state.timezone import now


AUTH_HEADERS = {"X-Operator-Token": "changeme"}


class StubSchedulerClient:
    def __init__(self, settings: Any) -> None:
        self.submissions: list[dict] = []
        self.cancellations: list[dict] = []

    async def submit_task(self, payload: dict) -> None:
        self.submissions.append(payload)

    async def cancel_task(self, payload: dict) -> None:
        self.cancellations.append(payload)

    async def aclose(self) -> None:
        return None


class _FakeRepository(TaskRepository):
    def __init__(self) -> None:
        self._store: dict[str, TaskRecord] = {}
        self._service_index: dict[str, set[str]] = defaultdict(set)
        self._service_user_index: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._service_users: dict[str, set[str]] = defaultdict(set)
        self._sequence = 0

    async def next_task_id(self) -> str:
        self._sequence += 1
        return str(self._sequence)

    async def save(self, task: TaskRecord) -> None:
        self._store[task.task_id] = task
        self._service_index[task.service].add(task.task_id)
        self._service_user_index[(task.service, task.user_id)].add(task.task_id)
        self._service_users[task.service].add(task.user_id)

    async def get(self, task_id: str) -> TaskRecord | None:
        return self._store.get(task_id)

    async def delete(self, task_id: str) -> None:
        task = self._store.pop(task_id, None)
        if not task:
            return
        self._service_index[task.service].discard(task_id)
        self._service_user_index[(task.service, task.user_id)].discard(task_id)
        if not self._service_user_index[(task.service, task.user_id)]:
            self._service_users[task.service].discard(task.user_id)

    async def set_status(
        self, task_id: str, status: TaskStatus, *, log_entry: str | None = None
    ) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = now()
        if log_entry:
            task.logs.append(format_log_entry(log_entry))
        await self.save(task)
        return task

    async def append_log(self, task_id: str, message: str) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        task.logs.append(format_log_entry(message))
        task.updated_at = now()
        await self.save(task)
        return task

    async def update_result(
        self,
        task_id: str,
        *,
        pod_status: str | None = None,
        launcher_output: str | None = None,
    ) -> TaskRecord | None:
        task = await self.get(task_id)
        if not task:
            return None
        updated = task.result.model_copy()
        changed = False
        if pod_status is not None:
            updated.pod_status = pod_status
            changed = True
        if launcher_output is not None:
            updated.launcher_output = launcher_output
            changed = True
        if not changed:
            return task
        task.result = updated
        task.updated_at = now()
        await self.save(task)
        return task

    async def list_by_ids(self, ids: Iterable[str]) -> list[TaskRecord]:
        return [self._store[task_id] for task_id in ids if task_id in self._store]

    async def list_all(self) -> list[TaskRecord]:
        return list(self._store.values())

    async def list_by_service(self, service: str) -> list[TaskRecord]:
        return [self._store[task_id] for task_id in self._service_index.get(service, set())]

    async def list_by_service_and_user(self, service: str, user_id: str) -> list[TaskRecord]:
        key = (service, user_id)
        return [self._store[task_id] for task_id in self._service_user_index.get(key, set())]

    async def list_users_by_service(self, service: str) -> list[str]:
        return list(self._service_users.get(service, set()))


class _FakeRedisProvider:
    should_fail = False

    class _FakeRedisClient:
        def __init__(self, *, should_fail: bool = False) -> None:
            self.should_fail = should_fail

        async def ping(self) -> bool:
            if self.should_fail:
                raise RuntimeError("redis unavailable")
            return True

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.repository = _FakeRepository()
        self.closed = False
        self.reader = self._FakeRedisClient(should_fail=self.should_fail)
        self.writer = self._FakeRedisClient(should_fail=self.should_fail)

    async def get_repository(self) -> _FakeRepository:
        return self.repository

    async def start_key_expiration_listener(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
async def test_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DMS_OPERATOR_TOKEN", "changeme")
    monkeypatch.setenv("DMS_REDIS_WRITE_URL", "redis://write")
    monkeypatch.setenv("DMS_REDIS_READ_URL", "redis://read")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    from app import services_container

    monkeypatch.setattr(services_container, "SchedulerClient", StubSchedulerClient)
    monkeypatch.setattr(services_container, "RedisRepositoryProvider", _FakeRedisProvider)

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
async def test_healthcheck_endpoint_is_public(test_app: AsyncClient) -> None:
    response = await test_app.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": {"connected": True}}

    response_with_token = await test_app.get("/healthz", headers=AUTH_HEADERS)
    assert response_with_token.status_code == 200
    assert response_with_token.json() == {"status": "ok", "redis": {"connected": True}}


@pytest.mark.asyncio
async def test_healthcheck_reports_redis_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMS_OPERATOR_TOKEN", "changeme")
    monkeypatch.setenv("DMS_REDIS_WRITE_URL", "redis://write")
    monkeypatch.setenv("DMS_REDIS_READ_URL", "redis://read")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    from app import services_container

    monkeypatch.setattr(services_container, "SchedulerClient", StubSchedulerClient)
    monkeypatch.setattr(services_container, "RedisRepositoryProvider", _FakeRedisProvider)
    monkeypatch.setattr(_FakeRedisProvider, "should_fail", True)

    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["redis"] == {"connected": False, "message": "redis unavailable"}


@pytest.mark.asyncio
async def test_help_endpoint_is_public(test_app: AsyncClient) -> None:
    response = await test_app.get("/api/v1/help")
    assert response.status_code == 200
    assert "X-Operator-Token" in response.json()["description"]


@pytest.mark.asyncio
async def test_user_routes_require_token(test_app: AsyncClient) -> None:
    response = await test_app.post("/api/v1/services/sync/users/alice/tasks")
    assert response.status_code == 401

    response = await test_app.post(
        "/api/v1/services/sync/users/alice/tasks", params={"input": "value"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_user_can_create_and_list_tasks(test_app: AsyncClient) -> None:
    create_response = await test_app.post(
        "/api/v1/services/sync/users/alice/tasks", params={"input": "value"}, headers=AUTH_HEADERS
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    async def _task_running() -> bool:
        response = await test_app.get(
            f"/api/v1/services/sync/tasks/{task_id}", params={"user_id": "alice"}, headers=AUTH_HEADERS
        )
        return response.status_code == 200 and response.json()["task"]["status"] in {"running", "completed"}

    await wait_for_condition(_task_running)

    status_response = await test_app.get(
        f"/api/v1/services/sync/tasks/{task_id}", params={"user_id": "alice"}, headers=AUTH_HEADERS
    )
    assert status_response.status_code == 200
    logs = status_response.json()["task"]["logs"]
    assert logs
    timestamp, message = logs[0].split(",", 1)
    datetime.fromisoformat(timestamp)
    assert message == "Dispatching to scheduler"

    list_response = await test_app.get("/api/v1/services/sync/users/alice/tasks", headers=AUTH_HEADERS)
    assert list_response.status_code == 200
    tasks = list_response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task_id


@pytest.mark.asyncio
async def test_operator_token_required(test_app: AsyncClient) -> None:
    response = await test_app.get("/api/v1/admin/tasks", headers={"X-Operator-Token": "wrong"})
    assert response.status_code == 401

    response = await test_app.get("/api/v1/admin/tasks", headers=AUTH_HEADERS)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_can_cancel_task(test_app: AsyncClient) -> None:
    create_response = await test_app.post("/api/v1/services/scan/users/bob/tasks", headers=AUTH_HEADERS)
    task_id = create_response.json()["task_id"]

    cancel_response = await test_app.post(
        f"/api/v1/services/scan/tasks/{task_id}/cancel", params={"user_id": "bob"}, headers=AUTH_HEADERS
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["task"]["status"] == "cancel_requested"

    async def _task_cancelled() -> bool:
        response = await test_app.get(
            f"/api/v1/services/scan/tasks/{task_id}", params={"user_id": "bob"}, headers=AUTH_HEADERS
        )
        return response.status_code == 200 and response.json()["task"]["status"] == "cancelled"

    await wait_for_condition(_task_cancelled)


@pytest.mark.asyncio
async def test_service_user_listing(test_app: AsyncClient) -> None:
    await test_app.post("/api/v1/services/sync/users/alice/tasks", headers=AUTH_HEADERS)
    await test_app.post("/api/v1/services/sync/users/bob/tasks", headers=AUTH_HEADERS)
    await test_app.post("/api/v1/services/scan/users/charlie/tasks", headers=AUTH_HEADERS)

    response = await test_app.get("/api/v1/services/sync/users", headers=AUTH_HEADERS)
    assert response.status_code == 200
    users = set(response.json()["users"])
    assert users == {"alice", "bob"}
