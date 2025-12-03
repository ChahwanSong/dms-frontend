from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SchedulerUnavailableError(RuntimeError):
    """Raised when the scheduler service cannot be reached."""

    def __init__(self, message: str, *, url: str, original: Exception) -> None:
        super().__init__(message)
        self.url = url
        self.original = original


class SchedulerResponseError(RuntimeError):
    """Raised when the scheduler responds with a non-success status code."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        status_code: int,
        response_text: str,
        original: Exception,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.response_text = response_text
        self.original = original


class SchedulerClient:
    """Client responsible for communicating with the scheduler microservice."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)

    async def submit_task(self, payload: Dict[str, Any]) -> None:
        url = self._settings.scheduler_url(self._settings.scheduler_task_endpoint)
        logger.debug("Submitting task to scheduler", extra={"url": url, "payload": payload})
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text
            status_code = exc.response.status_code
            logger.error(
                "Scheduler responded with error",
                extra={"url": url, "status_code": status_code, "response": response_text},
            )
            raise SchedulerResponseError(
                f"Scheduler responded with {status_code}: {response_text}",
                url=url,
                status_code=status_code,
                response_text=response_text,
                original=exc,
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Scheduler unreachable", extra={"url": url, "error": str(exc)}
            )
            raise SchedulerUnavailableError(
                f"Scheduler at {url} is unreachable: {exc}", url=url, original=exc
            ) from exc

    async def cancel_task(self, payload: Dict[str, Any]) -> None:
        url = self._settings.scheduler_url(self._settings.scheduler_cancel_endpoint)
        logger.debug("Cancelling task via scheduler", extra={"url": url, "payload": payload})
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text
            status_code = exc.response.status_code
            logger.error(
                "Scheduler responded with error",
                extra={"url": url, "status_code": status_code, "response": response_text},
            )
            raise SchedulerResponseError(
                f"Scheduler responded with {status_code}: {response_text}",
                url=url,
                status_code=status_code,
                response_text=response_text,
                original=exc,
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Scheduler unreachable", extra={"url": url, "error": str(exc)}
            )
            raise SchedulerUnavailableError(
                f"Scheduler at {url} is unreachable: {exc}", url=url, original=exc
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
