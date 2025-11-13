from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.services_container import init_services, shutdown_services

from .api.routes import meta, operator, user


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version)

    app.include_router(meta.router, prefix=settings.api_prefix)
    app.include_router(user.router, prefix=settings.api_prefix)
    app.include_router(operator.router, prefix=settings.api_prefix)

    @app.on_event("startup")
    async def _startup() -> None:
        await init_services(settings=settings)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await shutdown_services()

    return app


app = create_app()
