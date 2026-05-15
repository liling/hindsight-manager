import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.models.user import UserRole


def _make_admin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.username = "admin"
    u.display_name = "Admin"
    u.role = UserRole.ADMIN
    u.is_active = True
    u.email = "admin@test.com"
    u.auth_provider = MagicMock(value="local")
    return u


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def admin_client():
    admin_user = _make_admin()
    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return admin_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, mock_session
    app.dependency_overrides.clear()


async def test_task_stats_returns_global_and_per_tenant(admin_client):
    client, mock_session = admin_client

    # Mock: tenant list query
    tenant_row = MagicMock()
    tenant_row.id = uuid.uuid4()
    tenant_row.name = "测试租户"
    tenant_row.schema_name = "tenant_test"

    tenant_result = MagicMock()
    tenant_result.scalars.return_value.all.return_value = [tenant_row]
    # Session.execute calls: 1. tenant query, 2. SET search_path, 3. stats query, 4. RESET search_path
    mock_session.execute.side_effect = [
        tenant_result,  # tenant query
        MagicMock(),  # SET search_path TO tenant_test, public
        MagicMock(fetchall=lambda: [("pending", 5), ("processing", 2), ("completed", 100)]),  # stats query
        MagicMock(),  # SET search_path TO public
    ]

    resp = await client.get("/admin/api/task-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "global" in data
    assert "by_tenant" in data
    assert data["global"]["pending"] == 5
    assert data["global"]["processing"] == 2
    assert data["global"]["completed"] == 100
    assert len(data["by_tenant"]) == 1
    assert data["by_tenant"][0]["tenant_name"] == "测试租户"