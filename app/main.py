from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.services_container import init_services, shutdown_services

from .api.routes import meta, operator, user


def create_app() -> FastAPI:
    settings = get_settings()

    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await init_services(settings=settings)
        try:
            yield
        finally:
            await shutdown_services()

    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

    app.include_router(meta.health_router)
    app.include_router(meta.router, prefix=settings.api_prefix)
    app.include_router(user.router, prefix=settings.api_prefix)
    app.include_router(operator.router, prefix=settings.api_prefix)

    return app


app = create_app()
