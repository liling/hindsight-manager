import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.cas import CASAuth, CASClient
from hindsight_manager.auth.dependencies import SESSION_COOKIE, get_current_user, require_admin
from hindsight_manager.auth.local import verify_password
from hindsight_manager.auth.password import hash_password, validate_password_strength, PasswordStrengthError
from hindsight_manager.auth.session import create_access_token, create_otp, create_token, exchange_otp
from hindsight_manager.config import Settings
from hindsight_manager.crypto import decrypt_sm4
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey
from hindsight_manager.models.tenant import Tenant
from hindsight_manager.models.tenant_member import TenantMember
from hindsight_manager.models.user import AuthProvider, User

router = APIRouter(prefix="/auth", tags=["auth"])

templates = Jinja2Templates(directory="hindsight_manager/templates")


class LoginRequest(BaseModel):
    provider: str
    username: str | None = None
    password: str | None = None
    ticket: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    auth_provider: str


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        auth_provider=user.auth_provider.value,
    )


def _set_session(response: Response | JSONResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        max_age=86400,
        path="/",
        samesite="lax",
        secure=False
    )


@router.post("/login")
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    settings = Settings()

    if req.provider == "local":
        if not req.username or not req.password:
            raise HTTPException(status_code=400, detail="username and password required")
        result = await session.execute(select(User).where(User.username == req.username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash or ""):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_token(str(user.id), user.username, settings.jwt_secret)
        resp = JSONResponse(content={"token": token, "user": _user_response(user).model_dump()})
        _set_session(resp, token)
        return resp

    if req.provider == "cas":
        if not req.ticket:
            raise HTTPException(status_code=400, detail="ticket required")
        if not settings.cas_server_url or not settings.cas_service_url:
            raise HTTPException(status_code=500, detail="CAS not configured")
        cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
        cas_auth = CASAuth(cas_client, settings.jwt_secret)
        result = await cas_auth.authenticate(req.ticket)
        if not result:
            raise HTTPException(status_code=401, detail="CAS authentication failed")
        username = result["username"]
        db_result = await session.execute(select(User).where(User.username == username))
        user = db_result.scalar_one_or_none()
        if not user:
            user = User(username=username, display_name=username, auth_provider=AuthProvider.CAS)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        resp = JSONResponse(content={"token": result["token"], "user": _user_response(user).model_dump()})
        _set_session(resp, result["token"])
        return resp

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {req.provider}")


@router.post("/login/form")
async def login_form(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    settings = Settings()
    username = form.username
    password = form.password

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash or ""):
        return templates.TemplateResponse(
            request, "login.html", {"error": "用户名或密码错误"},
        )
    token = create_token(str(user.id), user.username, settings.jwt_secret)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    _set_session(resp, token)
    return resp


@router.get("/cas/login")
async def cas_login(request: Request):
    settings = Settings()
    if not settings.cas_server_url or not settings.cas_service_url:
        raise HTTPException(status_code=500, detail="CAS not configured")
    cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
    return RedirectResponse(url=cas_client.get_login_url())


@router.get("/cas/callback")
async def cas_callback(ticket: str, session: AsyncSession = Depends(get_session)):
    settings = Settings()
    cas_client = CASClient(settings.cas_server_url, settings.cas_service_url)
    cas_auth = CASAuth(cas_client, settings.jwt_secret)
    result = await cas_auth.authenticate(ticket)
    if not result:
        raise HTTPException(status_code=401, detail="CAS authentication failed")
    username = result["username"]
    db_result = await session.execute(select(User).where(User.username == username))
    user = db_result.scalar_one_or_none()
    if not user:
        user = User(username=username, display_name=username, auth_provider=AuthProvider.CAS)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    resp = JSONResponse(content={"user": _user_response(user).model_dump()})
    _set_session(resp, result["token"])
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return _user_response(current_user)


class AccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    tenant_id: str


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


@router.post("/access-token", response_model=AccessTokenResponse)
async def create_access_token_endpoint(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == current_user.id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    settings = Settings()
    token = create_access_token(
        user_id=str(current_user.id),
        tenant_id=str(tenant_id),
        secret=settings.jwt_secret,
    )
    return AccessTokenResponse(
        access_token=token,
        expires_in=900,
        tenant_id=str(tenant_id),
    )


@router.post("/otp", response_model=OtpResponse)
async def create_otp_endpoint(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == current_user.id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    otp = create_otp(str(current_user.id), str(tenant_id))
    settings = Settings()

    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    slug = tenant.schema_name if tenant else str(tenant_id)

    redirect_url = f"{settings.cp_url_for_tenant(slug)}/?otp={otp}"

    return OtpResponse(otp=otp, expires_in=60, redirect_url=redirect_url)


@router.post("/exchange-otp", response_model=ExchangeOtpResponse)
async def exchange_otp_endpoint(
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

    jwt_token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        secret=settings.jwt_secret,
    )

    return ExchangeOtpResponse(
        jwt=jwt_token,
        api_key=decrypted_key,
        tenant_slug=tenant.schema_name,
    )


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    display_name: str
    auth_provider: str = "local"


@router.post("/users", response_model=UserResponse)
async def create_user(
    req: CreateUserRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Create a new user (admin only)."""

    # Check if username already exists
    result = await session.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    # Validate password strength
    try:
        validate_password_strength(req.password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate auth provider
    if req.auth_provider not in ["local", "cas"]:
        raise HTTPException(status_code=400, detail="Invalid auth provider")

    # Create user
    user = User(
        username=req.username,
        password_hash=hash_password(req.password) if req.auth_provider == "local" else None,
        email=req.email,
        display_name=req.display_name,
        auth_provider=AuthProvider.LOCAL if req.auth_provider == "local" else AuthProvider.CAS,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return _user_response(user)
