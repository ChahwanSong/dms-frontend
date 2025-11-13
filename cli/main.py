from __future__ import annotations

from typing import Optional

import typer
import uvicorn

from app.core.config import get_settings

cli = typer.Typer(help="Command line interface for the DMS frontend service")


@cli.command()
def serve(
    host: Optional[str] = typer.Option(None, help="Host to bind the API server to"),
    port: Optional[int] = typer.Option(None, help="Port to bind the API server to"),
    reload: Optional[bool] = typer.Option(None, help="Enable auto reload (development only)"),
) -> None:
    settings = get_settings()
    host = host or settings.cli_default_host
    port = port or settings.cli_default_port
    reload = settings.cli_reload if reload is None else reload

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@cli.command()
def show_config() -> None:
    settings = get_settings()
    for field, value in settings.model_dump().items():
        typer.echo(f"{field}: {value}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
