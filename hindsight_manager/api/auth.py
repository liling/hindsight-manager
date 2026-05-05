from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.cas import CASAuth, CASClient
from hindsight_manager.auth.dependencies import SESSION_COOKIE, get_current_user
from hindsight_manager.auth.local import verify_password
from hindsight_manager.auth.session import create_token
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.models.user import AuthProvider, User

router = APIRouter(prefix="/auth", tags=["auth"])


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
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400, path="/")


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
        resp = JSONResponse(content={"token": token, "user": _user_response(user)})
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
        resp = JSONResponse(content={"token": result["token"], "user": _user_response(user)})
        _set_session(resp, result["token"])
        return resp

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {req.provider}")


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
    resp = JSONResponse(content={"user": _user_response(user)})
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
