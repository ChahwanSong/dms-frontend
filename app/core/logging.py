from __future__ import annotations

import logging
import sys
from typing import Any, Dict

from pythonjsonlogger.json import JsonFormatter

from .config import Settings


class KubernetesJSONFormatter(JsonFormatter):
    """JSON log formatter with Kubernetes friendly defaults."""

    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:  # noqa: D401 - documented in base
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("severity", record.levelname)
        log_record.setdefault("logger", record.name)
        if not log_record.get("message"):
            log_record["message"] = record.getMessage()


class AccessPathExclusionFilter(logging.Filter):
    """Filter that suppresses Uvicorn access logs for configurable paths."""

    def __init__(
        self,
        *,
        excluded_paths: tuple[str, ...] = ("/healthz",),
        match_prefix: bool = True,
    ) -> None:
        super().__init__()
        self.excluded_paths = tuple(excluded_paths)
        self.match_prefix = match_prefix

    @staticmethod
    def _extract_path(request_line: str) -> str | None:
        try:
            return request_line.split(" ", 2)[1]
        except IndexError:
            return None

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - documented in base
        if record.name != "uvicorn.access":
            return True

        path = self._extract_path(getattr(record, "request_line", ""))
        if path is None:
            return True

        for excluded_path in self.excluded_paths:
            if self.match_prefix and path.startswith(excluded_path):
                return False
            if not self.match_prefix and path == excluded_path:
                return False

        return True


def configure_logging(settings: Settings) -> None:
    """Configure application logging."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if settings.log_json:
        formatter = KubernetesJSONFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    handler.setFormatter(formatter)
    access_filter = AccessPathExclusionFilter(
        excluded_paths=settings.access_log_excluded_paths
    )
    handler.addFilter(access_filter)
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Reduce noise from third party libraries
    logging.getLogger("uvicorn").setLevel(settings.log_level)
    logging.getLogger("uvicorn.error").setLevel(settings.log_level)
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.setLevel(settings.log_level)
    uvicorn_access_logger.filters = [
        filter
        for filter in uvicorn_access_logger.filters
        if not isinstance(filter, AccessPathExclusionFilter)
    ]
    uvicorn_access_logger.addFilter(access_filter)
    logging.getLogger("httpx").setLevel(settings.log_level)
