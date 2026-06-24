import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none


def _dict_user(user_id="00000000-0000-0000-0000-000000000099", username="testuser", role="admin"):
    return {"id": user_id, "username": username, "role": role}


@pytest.fixture
async def client():
    async def _override_session():
        yield AsyncMock()

    user = _dict_user()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_or_none] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_root_redirects_to_dashboard_when_logged_in(client: AsyncClient):
    resp = await client.get("/hindsight/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/hindsight/dashboard" in resp.headers["location"]


@pytest.mark.asyncio
async def test_login_page_redirects_to_platform(client: AsyncClient):
    # /login now redirects to xinyi-platform's /oauth/authorize (HM no longer
    # renders a login page — login lives in the platform).
    app.dependency_overrides[get_current_user_or_none] = lambda: None
    resp = await client.get("/hindsight/login", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/oauth/authorize" in resp.headers["location"]


@pytest.mark.asyncio
async def test_dashboard_page_renders(client: AsyncClient):
    mock_result = MagicMock()
    mock_result.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.get("/hindsight/dashboard")
    assert resp.status_code == 200
    assert "记忆库" in resp.text
    assert "获取 MCP 配置" in resp.text
    assert 'id="mcp-config-modal"' in resp.text
    assert 'id="mcp-config-code"' in resp.text
    assert 'id="mcp-config-location"' in resp.text
    assert "window.MCP_URL" in resp.text
    assert ">MCP 地址<" not in resp.text
    assert "重命名" in resp.text
    assert 'id="rename-modal"' in resp.text
    assert 'id="rename-name"' in resp.text
    assert 'id="rename-tenant-id"' in resp.text


@pytest.mark.asyncio
async def test_dashboard_owner_card_renders_rename_icon(client: AsyncClient):
    tenant = MagicMock()
    tenant.id = "t-1"
    tenant.name = "Alice's Lab"
    tenant.schema_name = "tenant_x"
    role = MagicMock()
    role.value = "owner"

    mock_result = MagicMock()
    mock_result.all.return_value = [(tenant, role)]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.get("/hindsight/dashboard")
    assert resp.status_code == 200
    assert 'class="tenant-edit-btn"' in resp.text
    assert 'aria-label="重命名"' in resp.text
    assert "onclick='showRenameModal(" in resp.text
    assert '"Alice\\u0027s Lab"' in resp.text


@pytest.mark.asyncio
async def test_dashboard_member_card_has_no_rename_icon(client: AsyncClient):
    tenant = MagicMock()
    tenant.id = "t-1"
    tenant.name = "My Lab"
    tenant.schema_name = "tenant_x"
    role = MagicMock()
    role.value = "member"

    mock_result = MagicMock()
    mock_result.all.return_value = [(tenant, role)]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.get("/hindsight/dashboard")
    assert resp.status_code == 200
    assert "tenant-edit-btn" not in resp.text
