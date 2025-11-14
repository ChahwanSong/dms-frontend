"""Local stub scheduler for development and manual testing."""
from __future__ import annotations

import logging
import signal
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("dms-frontend.local-scheduler")


class _State:
    def __init__(self) -> None:
        self.tasks: dict[str, Dict[str, Any]] = {}


state = _State()


@asynccontextmanager
def lifespan(_: FastAPI):
    logger.info("Starting local scheduler stub")
    try:
        yield
    finally:
        state.tasks.clear()
        logger.info("Stopping local scheduler stub")


def create_app() -> FastAPI:
    app = FastAPI(title="DMS Scheduler Stub", version="0.1.0", lifespan=lifespan)

    @app.post("/task")
    async def submit_task(payload: Dict[str, Any]) -> JSONResponse:
        task_id = str(payload.get("task_id") or payload.get("id") or payload.get("uuid") or len(state.tasks) + 1)
        state.tasks[task_id] = payload
        logger.info("Accepted task", extra={"task_id": task_id, "payload": payload})
        return JSONResponse({"status": "accepted", "task_id": task_id})

    @app.post("/cancel")
    async def cancel_task(payload: Dict[str, Any]) -> JSONResponse:
        task_id = payload.get("task_id")
        if not task_id:
            raise HTTPException(status_code=400, detail="task_id is required")
        if task_id not in state.tasks:
            logger.warning("Received cancellation for unknown task", extra={"task_id": task_id})
        else:
            state.tasks[task_id]["cancelled"] = True
            logger.info("Cancelled task", extra={"task_id": task_id})
        return JSONResponse({"status": "cancelled", "task_id": task_id})

    return app


app = create_app()


def run(host: str = "127.0.0.1", port: int = 9000) -> None:
    """Entrypoint to run the scheduler stub with Uvicorn."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    def _handle_signal(*_: Any) -> None:
        server.should_exit = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Local scheduler stub listening", extra={"host": host, "port": port})
    try:
        server.run()
    except Exception:  # pragma: no cover - defensive logging hook
        logger.exception("Local scheduler stub crashed")
        raise


if __name__ == "__main__":
    run()
