from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jose import JWTError

from hindsight_manager.auth.session import decode_access_token
from hindsight_manager.config import Settings

SESSION_COOKIE = "hindsight_session"
SELF_AUDIENCE = "hm-prod"


def _get_settings() -> Settings:
    return Settings()


def _extract_token(cookie_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if cookie_token:
        return cookie_token
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


async def get_current_user(
    request: Request,
    hindsight_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(_get_settings),
) -> dict:
    token = _extract_token(hindsight_session, authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"Location": "/auth/login-redirect"},
        )
    try:
        payload = decode_access_token(
            token, settings.jwt_secret, audience=SELF_AUDIENCE,
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"Location": "/auth/login-redirect"},
        )
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return {
        "id": payload["sub"],
        "username": payload["username"],
        "role": payload["role"],
    }


async def get_current_user_or_none(
    request: Request,
    hindsight_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(_get_settings),
) -> dict | None:
    try:
        return await get_current_user(request, hindsight_session, authorization, settings)
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
