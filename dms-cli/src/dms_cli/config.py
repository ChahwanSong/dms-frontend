from __future__ import annotations

import ssl
from typing import Any, Optional, Union

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CLISettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", populate_by_name=True)

    frontend_url: str = Field(
        default="https://127.0.0.1:8000",
        validation_alias=AliasChoices("DMS_FRONTEND_URL", "dms_frontend_url"),
    )
    api_prefix: str = Field(
        default="/api/v1",
        validation_alias=AliasChoices("DMS_FRONTEND_API_PREFIX", "dms_frontend_api_prefix"),
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DMS_CLI_CA_BUNDLE", "dms_cli_ca_bundle"),
    )
    insecure_tls: bool = Field(
        default=False,
        validation_alias=AliasChoices("DMS_CLI_INSECURE", "dms_cli_insecure"),
    )
    timeout_seconds: float = Field(
        default=10.0,
        validation_alias=AliasChoices("DMS_CLI_TIMEOUT_SECONDS", "dms_cli_timeout_seconds"),
    )

    @property
    def api_base_url(self) -> str:
        return f"{self.frontend_url.rstrip('/')}/{self.api_prefix.strip('/')}"

    @property
    def httpx_verify(self) -> Union[bool, ssl.SSLContext]:
        if self.insecure_tls:
            return False
        if self.ca_bundle:
            return ssl.create_default_context(cafile=self.ca_bundle)
        return True

    def describe_environment(self) -> tuple[tuple[str, str, str], ...]:
        return (
            (
                "DMS_FRONTEND_URL",
                self.frontend_url,
                "dms-frontend base URL. Example: https://frontend.example:8000",
            ),
            (
                "DMS_FRONTEND_API_PREFIX",
                self.api_prefix,
                "versioned API root appended after the base URL",
            ),
            (
                "DMS_CLI_CA_BUNDLE",
                self.ca_bundle or "<system trust store>",
                "custom CA bundle path used for HTTPS verification",
            ),
            (
                "DMS_CLI_INSECURE",
                str(self.insecure_tls).lower(),
                "disable TLS verification for local testing only",
            ),
            (
                "DMS_CLI_TIMEOUT_SECONDS",
                str(self.timeout_seconds),
                "request timeout applied to every API call",
            ),
        )


def settings_from_overrides(**overrides: Any) -> CLISettings:
    return CLISettings(**overrides)
