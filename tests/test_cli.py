from __future__ import annotations

import io
import ssl
from typing import Any

import httpx
import pytest

from app.cli.client import DmsApiClient, DmsApiError
from app.cli.config import CLISettings
from app.cli.main import main
from app.cli.shell import AdminShell, KubeShell, UserShell


class FakeClient:
    def __init__(self, *, verify_response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.verify_response = verify_response or {"authenticated": True, "role": "operator"}
        self.operator_token: str | None = None
        self.user_tasks = [
            {"task_id": "10", "service": "sync", "status": "running", "user_id": "alice"},
            {"task_id": "11", "service": "rm", "status": "pending", "user_id": "alice"},
        ]

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def set_operator_token(self, token: str) -> None:
        self.operator_token = token
        self.calls.append(("set_operator_token", token))

    def verify_operator_token(self) -> dict[str, Any]:
        self.calls.append(("verify_operator_token", self.operator_token))
        return self.verify_response

    def health(self) -> dict[str, Any]:
        self.calls.append(("health",))
        return {"status": "ok", "redis": {"connected": True}}

    def list_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        self.calls.append(("list_tasks_by_user", user_id))
        return {"tasks": self.user_tasks}

    def list_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("list_user_tasks", service, user_id))
        return {"tasks": [task for task in self.user_tasks if task["service"] == service]}

    def create_task(self, service: str, user_id: str, parameters: dict[str, str]) -> dict[str, Any]:
        self.calls.append(("create_task", service, user_id, parameters))
        return {"task_id": "42", "status": "pending"}

    def get_task_status(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_status", service, task_id, user_id))
        return {"task": {"task_id": task_id, "service": service, "user_id": user_id, "status": "running"}}

    def cancel_task(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_task", service, task_id, user_id))
        return {"task": {"task_id": task_id, "service": service, "user_id": user_id, "status": "cancel_requested"}}

    def cleanup_task(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("cleanup_task", service, task_id, user_id))
        return {"task": {"task_id": task_id, "service": service, "user_id": user_id, "status": "cancel_requested"}}

    def cancel_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_tasks_by_user", user_id))
        return {"matched_count": 2, "affected_count": 2, "task_ids": ["10", "11"]}

    def cleanup_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        self.calls.append(("cleanup_tasks_by_user", user_id))
        return {"matched_count": 2, "affected_count": 2, "task_ids": ["10", "11"]}

    def cancel_service_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_service_user_tasks", service, user_id))
        return {"matched_count": 1, "affected_count": 1, "task_ids": ["10"]}

    def cleanup_service_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        self.calls.append(("cleanup_service_user_tasks", service, user_id))
        return {"matched_count": 1, "affected_count": 1, "task_ids": ["10"]}

    def list_all_tasks(self) -> dict[str, Any]:
        self.calls.append(("list_all_tasks",))
        return {"tasks": self.user_tasks}

    def get_next_task_id(self) -> dict[str, Any]:
        self.calls.append(("get_next_task_id",))
        return {"next_task_id": "12"}

    def list_service_tasks(self, service: str) -> dict[str, Any]:
        self.calls.append(("list_service_tasks", service))
        return {"tasks": [task for task in self.user_tasks if task["service"] == service]}

    def list_service_users(self, service: str) -> dict[str, Any]:
        self.calls.append(("list_service_users", service))
        return {"users": sorted({task["user_id"] for task in self.user_tasks if task["service"] == service})}

    def summarize_service_tasks(self, service: str) -> dict[str, Any]:
        self.calls.append(("summarize_service_tasks", service))
        return {
            "summary": {
                "service": service,
                "pending_task_ids": ["10"],
                "success_task_ids": [],
                "failed_task_ids": ["11"],
            }
        }

    def cancel_admin_task(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_admin_task", task_id))
        return {"task": {"task_id": task_id, "status": "cancel_requested"}}

    def cleanup_admin_task(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("cleanup_admin_task", task_id))
        return {"task": {"task_id": task_id, "status": "cancel_requested"}}

    def cancel_service_tasks(self, service: str) -> dict[str, Any]:
        self.calls.append(("cancel_service_tasks", service))
        return {"matched_count": 1, "affected_count": 1, "task_ids": ["10"]}

    def cleanup_service_tasks(self, service: str) -> dict[str, Any]:
        self.calls.append(("cleanup_service_tasks", service))
        return {"matched_count": 1, "affected_count": 1, "task_ids": ["10"]}


def make_settings() -> CLISettings:
    return CLISettings(
        frontend_url="https://frontend.example",
        api_prefix="/api/v1",
        insecure_tls=True,
        timeout_seconds=3.0,
    )


def test_user_shell_run_command_forwards_query_params() -> None:
    stdout = io.StringIO()
    client = FakeClient()
    shell = UserShell(client=client, settings=make_settings(), user_id="alice", stdout=stdout)

    status = shell.execute_command("run sync src=/home/gpu1 dst=/pvs/archive options='--delete --direct'")

    assert status == 0
    assert client.calls[0] == (
        "create_task",
        "sync",
        "alice",
        {"src": "/home/gpu1", "dst": "/pvs/archive", "options": "--delete --direct"},
    )
    assert '"task_id": "42"' in stdout.getvalue()


def test_user_shell_help_env_mentions_frontend_env_and_tls() -> None:
    stdout = io.StringIO()
    shell = UserShell(client=FakeClient(), settings=make_settings(), user_id="alice", stdout=stdout)

    status = shell.execute_command("help env")

    assert status == 0
    output = stdout.getvalue()
    assert "DMS_FRONTEND_URL" in output
    assert "DMS_CLI_CA_BUNDLE" in output
    assert "DMS_CLI_INSECURE" in output


def test_user_shell_completion_suggests_dynamic_services_and_task_ids() -> None:
    shell = UserShell(client=FakeClient(), settings=make_settings(), user_id="alice", stdout=io.StringIO())

    service_suggestions = shell.get_completion_suggestions("run ")
    task_suggestions = shell.get_completion_suggestions("get sync ")

    assert "sync" in service_suggestions
    assert "rm" in service_suggestions
    assert "10" in task_suggestions


def test_admin_shell_maps_service_summary_command() -> None:
    stdout = io.StringIO()
    client = FakeClient()
    shell = AdminShell(client=client, settings=make_settings(), stdout=stdout)

    status = shell.execute_command("summary service sync")

    assert status == 0
    assert client.calls[0] == ("summarize_service_tasks", "sync")
    assert '"pending_task_ids": [' in stdout.getvalue()


def test_kube_shell_hello_placeholder() -> None:
    stdout = io.StringIO()
    shell = KubeShell(settings=make_settings(), stdout=stdout)

    status = shell.execute_command("hello scheduler")

    assert status == 0
    assert "scheduler" in stdout.getvalue()


def test_cli_settings_builds_ssl_context_from_ca_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()

    def fake_create_default_context(*, cafile: str | None = None) -> object:
        assert cafile == "/tmp/dms-ca.pem"
        return sentinel

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)
    settings = CLISettings(frontend_url="https://frontend.example", ca_bundle="/tmp/dms-ca.pem", insecure_tls=False)

    assert settings.api_base_url == "https://frontend.example/api/v1"
    assert settings.httpx_verify == sentinel


def test_cli_settings_normalizes_frontend_url_when_api_prefix_included() -> None:
    settings = CLISettings(frontend_url="https://frontend.example/api/v1", api_prefix="/api/v1")

    assert settings.normalized_frontend_url == "https://frontend.example"
    assert settings.api_base_url == "https://frontend.example/api/v1"


def test_cli_settings_insecure_tls_defaults_to_true() -> None:
    settings = CLISettings(frontend_url="https://frontend.example")

    assert settings.insecure_tls is True
    assert settings.httpx_verify is False


def test_client_tls_error_message_recommends_bundle_or_insecure() -> None:
    settings = CLISettings(frontend_url="https://frontend.example", api_prefix="/api/v1")
    client = DmsApiClient(settings)

    def raise_tls_error(*args: Any, **kwargs: Any) -> Any:
        request = httpx.Request("GET", "https://frontend.example/healthz")
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] cert verify failed", request=request)

    client._client.request = raise_tls_error  # type: ignore[method-assign]

    with pytest.raises(DmsApiError) as exc_info:
        client.health()

    message = str(exc_info.value)
    assert "DMS_CLI_CA_BUNDLE" in message
    assert "DMS_CLI_INSECURE=true" in message


def test_main_admin_mode_requires_root(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("app.cli.main.is_root_user", lambda: False)

    status = main(["admin", "-c", "list tasks"])

    captured = capsys.readouterr()
    assert status == 1
    assert "root" in captured.err.lower()


def test_main_admin_mode_prompts_token_and_verifies(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient()

    monkeypatch.setattr("app.cli.main.is_root_user", lambda: True)
    monkeypatch.setattr("app.cli.main.prompt_operator_token", lambda: "secret-token")
    monkeypatch.setattr("app.cli.main.DmsApiClient", lambda settings: client)

    status = main(["admin", "-c", "list tasks"])

    captured = capsys.readouterr()
    assert status == 0
    assert ("set_operator_token", "secret-token") in client.calls
    assert ("verify_operator_token", "secret-token") in client.calls
    assert '"task_id": "10"' in captured.out


def test_main_user_mode_runs_without_explicit_mode(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient()

    monkeypatch.setattr("app.cli.main.DmsApiClient", lambda settings: client)
    monkeypatch.setattr("app.cli.main.resolve_cli_user_id", lambda: "alice")

    status = main(["-c", "help run"])

    captured = capsys.readouterr()
    assert status == 0
    assert "run <service> [key=value ...]" in captured.out
