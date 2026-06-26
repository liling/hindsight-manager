import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

# Set required env vars before importing the app, so Settings() can be built.
os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret-for-proxy")

from hindsight_manager.main import app  # noqa: E402
from hindsight_manager.db import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    # Provide a no-op DB session generator so FastAPI dependency resolution
    # reaches the auth check without crashing on "Database not initialized".
    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_proxy_missing_auth(client: AsyncClient):
    resp = await client.get("/hindsight/api/proxy/00000000-0000-0000-0000-000000000001/banks")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing authorization token"


async def test_proxy_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/hindsight/api/proxy/00000000-0000-0000-0000-000000000001/banks",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired token"
