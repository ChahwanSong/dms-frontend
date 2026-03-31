from __future__ import annotations

from typing import Any, Optional, Union

import httpx

from .config import CLISettings


class DmsApiError(RuntimeError):
    pass


class DmsApiClient:
    def __init__(self, settings: CLISettings) -> None:
        self.settings = settings
        self.operator_token: Optional[str] = None
        self._client = httpx.Client(
            base_url=settings.normalized_frontend_url,
            timeout=settings.timeout_seconds,
            verify=settings.httpx_verify,
        )

    def __enter__(self) -> DmsApiClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def set_operator_token(self, token: str) -> None:
        self.operator_token = token

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz", api=False)

    def get_frontend_help(self) -> dict[str, Any]:
        return self._request("GET", "/help")

    def verify_operator_token(self) -> dict[str, Any]:
        return self._request("GET", "/admin/auth/verify", operator=True)

    def list_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/services/{service}/users/{user_id}/tasks")

    def create_task(self, service: str, user_id: str, parameters: dict[str, str]) -> dict[str, Any]:
        return self._request("POST", f"/services/{service}/users/{user_id}/tasks", params=parameters)

    def cancel_service_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        return self._request("POST", f"/services/{service}/users/{user_id}/tasks/cancel")

    def cleanup_service_user_tasks(self, service: str, user_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/services/{service}/users/{user_id}/tasks")

    def list_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/services/users/{user_id}/tasks")

    def cancel_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", f"/services/users/{user_id}/tasks/cancel")

    def cleanup_tasks_by_user(self, user_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/services/users/{user_id}/tasks")

    def get_task_status(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/services/{service}/tasks/{task_id}", params={"user_id": user_id})

    def cancel_task(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        return self._request("POST", f"/services/{service}/tasks/{task_id}/cancel", params={"user_id": user_id})

    def cleanup_task(self, service: str, task_id: str, user_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/services/{service}/tasks/{task_id}", params={"user_id": user_id})

    def list_all_tasks(self) -> dict[str, Any]:
        return self._request("GET", "/admin/tasks", operator=True)

    def get_next_task_id(self) -> dict[str, Any]:
        return self._request("GET", "/admin/tasks/next-id", operator=True)

    def cancel_admin_task(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/admin/tasks/{task_id}/cancel", operator=True)

    def cleanup_admin_task(self, task_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/admin/tasks/{task_id}", operator=True)

    def list_service_users(self, service: str) -> dict[str, Any]:
        return self._request("GET", f"/admin/services/{service}/users", operator=True)

    def list_service_tasks(self, service: str) -> dict[str, Any]:
        return self._request("GET", f"/admin/services/{service}/tasks", operator=True)

    def cancel_service_tasks(self, service: str) -> dict[str, Any]:
        return self._request("POST", f"/admin/services/{service}/tasks/cancel", operator=True)

    def cleanup_service_tasks(self, service: str) -> dict[str, Any]:
        return self._request("DELETE", f"/admin/services/{service}/tasks", operator=True)

    def summarize_service_tasks(self, service: str) -> dict[str, Any]:
        return self._request("GET", f"/admin/services/{service}/tasks/summary", operator=True)

    def admin_metrics(self) -> dict[str, Any]:
        return self._request("GET", "/admin/metrics", operator=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
        operator: bool = False,
        api: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if operator:
            if not self.operator_token:
                raise DmsApiError("Operator token is not set for this admin request.")
            headers["X-Operator-Token"] = self.operator_token

        request_path = self._api_path(path) if api else path
        try:
            response = self._client.request(method, request_path, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DmsApiError(self._format_http_error(exc)) from exc
        except httpx.RequestError as exc:
            message = f"Request to {exc.request.url} failed: {exc}"
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                message += (
                    "\nTLS verification failed. Set DMS_CLI_CA_BUNDLE to your CA certificate path, "
                    "or set DMS_CLI_INSECURE=true for local testing only."
                )
            raise DmsApiError(message) from exc

        if not response.content:
            return {}
        return response.json()

    def _api_path(self, path: str) -> str:
        prefix = self.settings.api_prefix.rstrip("/")
        route = path if path.startswith("/") else f"/{path}"
        return f"{prefix}{route}"

    @staticmethod
    def _format_http_error(exc: httpx.HTTPStatusError) -> str:
        response = exc.response
        detail = response.text
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and "detail" in payload:
            detail = str(payload["detail"])
        return f"{response.status_code} {response.request.method} {response.request.url.path}: {detail}"
