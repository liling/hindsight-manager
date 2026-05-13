import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.models.user import User, UserRole


def _make_user(role=UserRole.USER, username="testuser"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.username = username
    u.display_name = "Test"
    u.role = role
    u.is_active = True
    u.email = "test@test.com"
    u.auth_provider = MagicMock(value="local")
    return u


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def admin_client():
    admin_user = _make_user(UserRole.ADMIN, "admin")

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


@pytest.fixture
async def normal_client():
    normal_user = _make_user(UserRole.USER, "normal")

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


async def test_list_users_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.get("/admin/users")
    assert resp.status_code == 403


async def test_list_users_admin_allowed(admin_client):
    client, mock_session = admin_client
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    resp = await client.get("/admin/users")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
    assert "items" in resp.json()


async def test_create_user_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.post("/admin/users", json={
        "username": "newuser",
        "password": "StrongPass123!",
        "display_name": "New User",
    })
    assert resp.status_code == 403


async def test_create_user_weak_password_rejected(admin_client):
    client, mock_session = admin_client
    resp = await client.post("/admin/users", json={
        "username": "newuser",
        "password": "weak",
        "display_name": "New User",
    })
    assert resp.status_code == 400


async def test_create_user_success(admin_client):
    client, mock_session = admin_client
    # No existing user: execute returns a mock where scalar_one_or_none() is None
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_result

    def mock_refresh(obj):
        """Fill in server defaults that SQLAlchemy would normally populate."""
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()
        if not hasattr(obj, "is_active") or obj.is_active is None:
            obj.is_active = True
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = "2025-01-01T00:00:00"
        if not hasattr(obj, "last_login_at"):
            obj.last_login_at = None

    mock_session.refresh = AsyncMock(side_effect=mock_refresh)

    with patch("hindsight_manager.api.admin.hash_password", return_value="$2b$12$hashed"):
        resp = await client.post("/admin/users", json={
            "username": "newuser",
            "password": "StrongPass123!",
            "display_name": "New User",
        })

    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["role"] == "user"


async def test_create_user_duplicate_username(admin_client):
    client, mock_session = admin_client
    # Existing user found: scalar_one_or_none() returns a truthy value
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = MagicMock()
    mock_session.execute.return_value = mock_execute_result

    resp = await client.post("/admin/users", json={
        "username": "existinguser",
        "password": "StrongPass123!",
        "display_name": "Existing User",
    })
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]


async def test_update_user_requires_admin(normal_client: AsyncClient):
    user_id = uuid.uuid4()
    resp = await normal_client.patch(f"/admin/users/{user_id}", json={
        "display_name": "Updated",
    })
    assert resp.status_code == 403


async def test_update_user_not_found(admin_client):
    client, mock_session = admin_client
    mock_session.get.return_value = None

    user_id = uuid.uuid4()
    resp = await client.patch(f"/admin/users/{user_id}", json={
        "display_name": "Updated",
    })
    assert resp.status_code == 404


async def test_delete_user_requires_admin(normal_client: AsyncClient):
    user_id = uuid.uuid4()
    resp = await normal_client.delete(f"/admin/users/{user_id}")
    assert resp.status_code == 403


async def test_disable_user_not_found(admin_client):
    client, mock_session = admin_client
    mock_session.get.return_value = None

    user_id = uuid.uuid4()
    resp = await client.delete(f"/admin/users/{user_id}")
    assert resp.status_code == 404


async def test_reset_password_requires_admin(normal_client: AsyncClient):
    user_id = uuid.uuid4()
    resp = await normal_client.post(f"/admin/users/{user_id}/reset-password", json={
        "new_password": "NewStrong123!",
    })
    assert resp.status_code == 403


async def test_reset_password_weak_rejected(admin_client):
    client, mock_session = admin_client
    user = _make_user(UserRole.USER, "targetuser")
    mock_session.get.return_value = user

    user_id = uuid.uuid4()
    resp = await client.post(f"/admin/users/{user_id}/reset-password", json={
        "new_password": "weak",
    })
    assert resp.status_code == 400
