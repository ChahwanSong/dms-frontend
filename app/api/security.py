from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.services_container import get_settings_instance


async def require_operator_token(x_operator_token: str = Header(..., alias="X-Operator-Token")) -> str:
    settings = get_settings_instance()
    if x_operator_token != settings.operator_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")
    return x_operator_token
