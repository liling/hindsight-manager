import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.auth.session import (
    create_access_token,
    create_otp,
    exchange_otp,
)
from hindsight_manager.config import Settings
from hindsight_manager.crypto import decrypt_sm4
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import TenantMember
from hindsight_manager.platform.client import XinyiPlatformClient
from hindsight_manager.platform.config import PlatformSettings

router = APIRouter(prefix="/auth", tags=["auth"])


def get_platform_settings() -> PlatformSettings:
    return PlatformSettings.from_app_settings(Settings())


@asynccontextmanager
async def get_platform_client():
    settings = get_platform_settings()
    client = XinyiPlatformClient(settings)
    try:
        yield client
    finally:
        await client.aclose()


def _set_session_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    response.set_cookie(
        "hindsight_session", access,
        httponly=True, max_age=settings.access_token_ttl_seconds,
        path="/", samesite="lax", secure=settings.session_secure,
    )
    response.set_cookie(
        "hindsight_refresh", refresh,
        httponly=True, max_age=settings.refresh_token_ttl_days * 86400,
        path="/auth", samesite="lax", secure=settings.session_secure,
    )


# ---------------------------------------------------------------------------
# OAuth2 client endpoints
# ---------------------------------------------------------------------------

@router.get("/login-redirect")
async def login_redirect(
    request: Request,
    return_to: str = Query("/"),
):
    settings = Settings()
    ps = get_platform_settings()
    state_raw = generate_oauth_state_helper()
    signature = sign_oauth_state_helper(state_raw, settings.jwt_secret)

    params = {
        "response_type": "code",
        "client_id": ps.oauth_client_id,
        "redirect_uri": ps.oauth_redirect_uri,
        "state": signature,
        "return_to": return_to,
    }
    authorize_url = f"{ps.platform_url}/oauth/authorize?{urlencode(params)}"

    resp = RedirectResponse(url=authorize_url, status_code=303)
    resp.set_cookie(
        "hm_oauth_state", signature,
        httponly=True, max_age=600, path="/auth", samesite="lax",
    )
    return resp


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    return_to: str = Query("/"),
    state_cookie: str | None = Cookie(default=None, alias="hm_oauth_state"),
):
    if not state_cookie or state_cookie != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    settings = Settings()
    ps = get_platform_settings()

    async with get_platform_client() as client:
        token_pair = await client.exchange_oauth_code(
            code=code, redirect_uri=ps.oauth_redirect_uri,
        )

    if token_pair is None:
        raise HTTPException(status_code=401, detail="OAuth code exchange failed")

    resp = RedirectResponse(url=return_to, status_code=303)
    _set_session_cookies(resp, token_pair["access_token"], token_pair["refresh_token"], settings)
    resp.delete_cookie("hm_oauth_state", path="/auth")
    return resp


@router.post("/refresh")
async def refresh_endpoint(
    request: Request,
    hindsight_refresh: str | None = Cookie(default=None),
):
    if not hindsight_refresh:
        raise HTTPException(status_code=401, detail="No refresh token")
    settings = Settings()

    async with get_platform_client() as client:
        new_pair = await client.refresh_token(hindsight_refresh)

    if new_pair is None:
        raise HTTPException(status_code=401, detail="Refresh failed")

    resp = JSONResponse(content={"ok": True, "expires_in": new_pair["expires_in"]})
    _set_session_cookies(resp, new_pair["access_token"], new_pair["refresh_token"], settings)
    return resp


@router.post("/logout")
async def logout(
    request: Request,
    hindsight_refresh: str | None = Cookie(default=None),
):
    settings = Settings()

    async with get_platform_client() as client:
        if hindsight_refresh:
            # Revoke all refresh tokens + add TokenRevocation on the platform
            await client.revoke_user_session(hindsight_refresh)

    platform_logout_url = (
        f"{settings.platform_url}/logout"
        f"?return_to={settings.base_url}/login"
    )
    resp = RedirectResponse(url=platform_logout_url, status_code=303)
    resp.delete_cookie("hindsight_session", path="/")
    resp.delete_cookie("hindsight_refresh", path="/auth")
    return resp


# ---------------------------------------------------------------------------
# Data-plane access token (unchanged logic, dict current_user)
# ---------------------------------------------------------------------------

class AccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    tenant_id: str


@router.post("/access-token", response_model=AccessTokenResponse)
async def create_access_token_endpoint(
    tenant_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(current_user["id"])
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    settings = Settings()
    token = create_access_token(str(user_id), str(tenant_id), settings.jwt_secret)
    return AccessTokenResponse(access_token=token, expires_in=900, tenant_id=str(tenant_id))


# ---------------------------------------------------------------------------
# Control-plane OTP flow (unchanged logic, dict current_user)
# ---------------------------------------------------------------------------

class OtpResponse(BaseModel):
    otp: str
    expires_in: int
    redirect_url: str


class ExchangeOtpRequest(BaseModel):
    otp: str


class ExchangeOtpResponse(BaseModel):
    jwt: str
    api_key: str
    tenant_slug: str


@router.post("/otp", response_model=OtpResponse)
async def create_otp_endpoint(
    tenant_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(current_user["id"])
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == user_id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    otp = create_otp(str(user_id), str(tenant_id))
    settings = Settings()

    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    slug = tenant.schema_name if tenant else str(tenant_id)
    redirect_url = f"{settings.cp_url_for_tenant(slug)}/"

    return OtpResponse(otp=otp, expires_in=60, redirect_url=redirect_url)


@router.get("/otp/redirect", response_class=HTMLResponse)
async def otp_redirect_form(otp: str, cp_url: str):
    import html as html_lib
    escaped_otp = html_lib.escape(otp)
    escaped_url = html_lib.escape(cp_url)
    content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Redirecting...</title></head>
<body>
<form id="f" method="POST" action="{escaped_url}">
  <input type="hidden" name="otp" value="{escaped_otp}">
</form>
<p>Redirecting...</p>
<script>document.getElementById('f').submit()</script>
</body></html>"""
    return HTMLResponse(content=content)


@router.post("/exchange-otp", response_model=ExchangeOtpResponse)
async def exchange_otp_endpoint(
    request: Request,
    req: ExchangeOtpRequest,
    session: AsyncSession = Depends(get_session),
):
    claims = exchange_otp(req.otp)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    user_id = claims["user_id"]
    tenant_id = claims["tenant_id"]

    settings = Settings()
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.tenant_id == tenant_id,
            ApiKey.is_system == True,  # noqa: E712
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key or not api_key.encrypted_key:
        raise HTTPException(status_code=500, detail="No system API key found for tenant")

    encryption_key_bytes = bytes.fromhex(settings.encryption_key)
    decrypted_key = decrypt_sm4(api_key.encrypted_key, encryption_key_bytes)

    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    jwt_token = create_access_token(user_id, tenant_id, settings.jwt_secret)

    return ExchangeOtpResponse(
        jwt=jwt_token,
        api_key=decrypted_key,
        tenant_slug=tenant.schema_name,
    )


# Helper wrappers (avoid circular import with auth.oauth_state)
def generate_oauth_state_helper() -> str:
    from hindsight_manager.auth.oauth_state import generate_oauth_state
    return generate_oauth_state()


def sign_oauth_state_helper(state: str, secret: str) -> str:
    from hindsight_manager.auth.oauth_state import sign_oauth_state
    return sign_oauth_state(state, secret)
