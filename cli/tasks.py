from __future__ import annotations

from typing import Dict, List

import httpx
import typer

DEFAULT_TIMEOUT = 10.0


def _parse_params(params: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for item in params:
        if "=" not in item:
            raise typer.BadParameter("Parameters must be in key=value format")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def _build_client(api_base: str) -> httpx.Client:
    base_url = api_base.rstrip("/")
    return httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)


def _echo_response(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:  # pragma: no cover - exercised via CLI
        typer.echo(f"Request failed ({exc.response.status_code}): {exc.response.text}")
        raise typer.Exit(code=1)
    except httpx.RequestError as exc:  # pragma: no cover - exercised via CLI
        typer.echo(f"Request error: {exc}")
        raise typer.Exit(code=1)

    typer.echo(response.text)


tasks_app = typer.Typer(help="Interact with task APIs via HTTP")


@tasks_app.command("list")
def list_tasks(
    service: str = typer.Option(..., "--service", help="Service name (e.g. sync)"),
    user: str = typer.Option(..., "--user", help="User identifier"),
    api_base: str = typer.Option(..., "--api-base", envvar="DMS_API_BASE", help="Base API URL (e.g. http://localhost:8000/api/v1)"),
) -> None:
    """List tasks for a user."""
    with _build_client(api_base) as client:
        response = client.get(f"/services/{service}/users/{user}/tasks")
    _echo_response(response)


@tasks_app.command("submit")
def submit_task(
    service: str = typer.Option(..., "--service", help="Service name (e.g. sync)"),
    user: str = typer.Option(..., "--user", help="User identifier"),
    param: List[str] = typer.Option([], "--param", help="Task parameter key=value pair", metavar="KEY=VALUE"),
    api_base: str = typer.Option(..., "--api-base", envvar="DMS_API_BASE", help="Base API URL (e.g. http://localhost:8000/api/v1)"),
) -> None:
    """Submit a task with query parameters."""
    parameters = _parse_params(param)
    with _build_client(api_base) as client:
        response = client.post(f"/services/{service}/users/{user}/tasks", params=parameters)
    _echo_response(response)


@tasks_app.command("cancel")
def cancel_task(
    service: str = typer.Option(..., "--service", help="Service name (e.g. sync)"),
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    user: str = typer.Option(..., "--user", help="User identifier"),
    api_base: str = typer.Option(..., "--api-base", envvar="DMS_API_BASE", help="Base API URL (e.g. http://localhost:8000/api/v1)"),
) -> None:
    """Request cancellation of a user task."""
    with _build_client(api_base) as client:
        response = client.post(f"/services/{service}/tasks/{task_id}/cancel", params={"user_id": user})
    _echo_response(response)


@tasks_app.command("delete")
def delete_task(
    service: str = typer.Option(..., "--service", help="Service name (e.g. sync)"),
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    user: str = typer.Option(..., "--user", help="User identifier"),
    api_base: str = typer.Option(..., "--api-base", envvar="DMS_API_BASE", help="Base API URL (e.g. http://localhost:8000/api/v1)"),
) -> None:
    """Delete stored task metadata and logs for a user."""
    with _build_client(api_base) as client:
        response = client.delete(f"/services/{service}/tasks/{task_id}", params={"user_id": user})
    _echo_response(response)


@tasks_app.command("users")
def list_users(
    service: str = typer.Option(..., "--service", help="Service name (e.g. sync)"),
    api_base: str = typer.Option(..., "--api-base", envvar="DMS_API_BASE", help="Base API URL (e.g. http://localhost:8000/api/v1)"),
) -> None:
    """List users who have submitted tasks for a service."""
    with _build_client(api_base) as client:
        response = client.get(f"/services/{service}/users")
    _echo_response(response)
