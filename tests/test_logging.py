import logging

from app.core.config import settings_from_overrides
from app.core.logging import AccessPathExclusionFilter, configure_logging


def _make_record(path: str, name: str = "uvicorn.access") -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    record.request_line = f"GET {path} HTTP/1.1"
    return record


def test_access_filter_excludes_configured_prefixes() -> None:
    access_filter = AccessPathExclusionFilter(excluded_paths=("/healthz", "/metrics"))

    assert access_filter.filter(_make_record("/metrics")) is False
    assert access_filter.filter(_make_record("/metrics/daily")) is False


def test_access_filter_allows_non_excluded_paths() -> None:
    access_filter = AccessPathExclusionFilter(excluded_paths=("/healthz",))

    assert access_filter.filter(_make_record("/api/v1/items")) is True
    assert access_filter.filter(_make_record("/healthz", name="custom.logger")) is True


def test_configure_logging_applies_excluded_paths() -> None:
    settings = settings_from_overrides(access_log_excluded_paths=("/metrics", "/status"))

    root_logger = logging.getLogger()
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    root_handlers = list(root_logger.handlers)
    root_level = root_logger.level
    uvicorn_filters = list(uvicorn_access_logger.filters)
    uvicorn_level = uvicorn_access_logger.level

    try:
        configure_logging(settings)

        handler_filter = next(
            filter
            for filter in root_logger.handlers[0].filters
            if isinstance(filter, AccessPathExclusionFilter)
        )
        assert handler_filter.excluded_paths == ("/metrics", "/status")

        access_filter = next(
            filter
            for filter in uvicorn_access_logger.filters
            if isinstance(filter, AccessPathExclusionFilter)
        )
        assert access_filter.excluded_paths == ("/metrics", "/status")
    finally:
        root_logger.handlers = root_handlers
        root_logger.setLevel(root_level)
        uvicorn_access_logger.filters = uvicorn_filters
        uvicorn_access_logger.setLevel(uvicorn_level)
