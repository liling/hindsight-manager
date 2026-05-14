import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.session import verify_access_token
from hindsight_manager.config import Settings
from hindsight_manager.crypto import decrypt_sm4
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey

router = APIRouter(tags=["proxy"])

settings = Settings()
http_client = httpx.AsyncClient(timeout=30.0)


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _resolve_system_key(session: AsyncSession, tenant_id: str) -> str:
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
    return decrypt_sm4(api_key.encrypted_key, encryption_key_bytes)


@router.api_route(
    "/api/proxy/{tenant_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_route(
    request: Request,
    tenant_id: str,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    # Validate access token
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    payload = verify_access_token(token, settings.jwt_secret, tenant_id)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Resolve system API key
    system_key = await _resolve_system_key(session, tenant_id)

    # Build upstream URL
    upstream_url = f"{settings.dataplane_url}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Prepare headers
    headers = {}
    if "content-type" in request.headers:
        headers["content-type"] = request.headers["content-type"]
    headers["authorization"] = system_key

    # Read body
    body = await request.body()

    # Forward request
    try:
        upstream_resp = await http_client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body if body else None,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream timeout")

    # Only forward safe response headers from upstream
    _SAFE_HEADERS = frozenset({
        "content-type",
        "content-disposition",
        "cache-control",
        "etag",
        "x-request-id",
    })
    response_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() in _SAFE_HEADERS
    }

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )
