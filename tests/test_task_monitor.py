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
    exists_result = MagicMock()
    exists_result.scalar.return_value = True
    stats_result = MagicMock()
    stats_result.fetchall.return_value = [("pending", 5), ("processing", 2), ("completed", 100)]
    # 1. tenant query, 2. SET search_path, 3. EXISTS check, 4. stats query, 5. SET search_path public
    mock_session.execute.side_effect = [
        tenant_result,
        MagicMock(),
        exists_result,
        stats_result,
        MagicMock(),
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


async def test_task_details_returns_paginated_items(admin_client):
    client, mock_session = admin_client

    # Mock: tenant lookup via session.get
    tenant_row = MagicMock()
    tenant_row.id = uuid.uuid4()
    tenant_row.name = "测试租户"
    tenant_row.schema_name = "tenant_test"

    mock_session.get = AsyncMock(return_value=tenant_row)

    # Mock: execute calls — SET search_path, EXISTS check, count query, data query, RESET search_path
    exists_result = MagicMock()
    exists_result.scalar.return_value = True
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    op_id = uuid.uuid4()
    op_row = (
        op_id,              # operation_id
        "consolidation",    # operation_type
        "processing",       # status
        0,                  # retry_count
        "worker-1",         # worker_id
        "2026-05-15T10:00:00",  # created_at
        "2026-05-15T10:01:00",  # updated_at
        None,               # completed_at
        None,               # error_message
    )

    data_result = MagicMock()
    data_result.fetchall.return_value = [op_row]

    mock_session.execute.side_effect = [
        MagicMock(),  # SET search_path TO tenant_test, public
        exists_result,  # EXISTS check
        count_result,  # SELECT COUNT(*)
        data_result,   # SELECT ... LIMIT OFFSET
        MagicMock(),  # SET search_path TO public
    ]

    resp = await client.get(
        "/admin/api/task-details",
        params={"tenant_id": str(tenant_row.id), "page": 1, "page_size": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["operation_type"] == "consolidation"


@pytest.fixture
async def normal_client():
    normal_user = MagicMock()
    normal_user.id = uuid.uuid4()
    normal_user.username = "normal"
    normal_user.display_name = "Normal"
    normal_user.role = UserRole.USER
    normal_user.is_active = True
    normal_user.email = "normal@test.com"
    normal_user.auth_provider = MagicMock(value="local")

    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return normal_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_task_stats_requires_admin(normal_client):
    resp = await normal_client.get("/admin/api/task-stats")
    assert resp.status_code == 403


async def test_task_details_requires_admin(normal_client):
    resp = await normal_client.get("/admin/api/task-details")
    assert resp.status_code == 403


async def test_task_stats_empty_when_no_tenants(admin_client):
    client, mock_session = admin_client
    tenant_result = MagicMock()
    tenant_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = tenant_result

    resp = await client.get("/admin/api/task-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["global"]["pending"] == 0
    assert data["by_tenant"] == []


async def test_task_details_empty_when_no_tenant_match(admin_client):
    client, mock_session = admin_client
    mock_session.get = AsyncMock(return_value=None)

    resp = await client.get(
        "/admin/api/task-details",
        params={"tenant_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0