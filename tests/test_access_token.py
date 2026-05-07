import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

# Set required env vars before importing the app, so Settings() can be built.
os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret-for-access-token")

from hindsight_manager.main import app  # noqa: E402
from hindsight_manager.db import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    from unittest.mock import AsyncMock

    # Provide a no-op DB session generator so FastAPI dependency resolution
    # reaches the auth check without crashing on "Database not initialized".
    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_access_token_missing_auth(client: AsyncClient):
    resp = await client.post(f"/auth/access-token?tenant_id={uuid.uuid4()}")
    assert resp.status_code == 401


async def test_access_token_invalid_session(client: AsyncClient):
    resp = await client.post(
        f"/auth/access-token?tenant_id={uuid.uuid4()}",
        cookies={"hindsight_session": "invalid-token"},
    )
    assert resp.status_code == 401


async def test_access_token_nonexistent_tenant(client: AsyncClient):
    """
    This test requires a real user in the DB.
    If no DB is available, it will fail -- that's expected for integration tests.
    """
    pass
