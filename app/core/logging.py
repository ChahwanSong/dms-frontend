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
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Reduce noise from third party libraries
    logging.getLogger("uvicorn").setLevel(settings.log_level)
    logging.getLogger("uvicorn.error").setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").setLevel(settings.log_level)
    logging.getLogger("httpx").setLevel(settings.log_level)
