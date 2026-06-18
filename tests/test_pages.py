import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.auth.dependencies import get_current_user, get_current_user_or_none


@pytest.fixture
async def client():
    async def _override_session():
        yield AsyncMock()

    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.username = "testuser"
    mock_user.display_name = "Test User"

    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_user_or_none] = lambda: mock_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_root_redirects_to_dashboard_when_logged_in(client: AsyncClient):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["location"]


@pytest.mark.asyncio
async def test_login_page_renders(client: AsyncClient):
    # Override to return None (unauthenticated user) so login page renders
    app.dependency_overrides[get_current_user_or_none] = lambda: None
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "Hindsight" in resp.text
    assert "登录" in resp.text


@pytest.mark.asyncio
async def test_dashboard_page_renders(client: AsyncClient):
    # The dashboard queries tenants from the DB via session.execute().
    # The default mock session's execute returns an AsyncMock whose .all()
    # is also an AsyncMock (returns a coroutine). We need a proper mock result.
    mock_result = MagicMock()
    mock_result.all.return_value = []  # empty tenant list

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "记忆库" in resp.text
    # MCP config dialog: new button replaces the old static MCP URL row
    assert "获取 MCP 配置" in resp.text
    assert 'id="mcp-config-modal"' in resp.text
    assert 'id="mcp-config-code"' in resp.text
    assert 'id="mcp-config-location"' in resp.text
    assert "window.MCP_URL" in resp.text
    # Old static MCP URL display row should be gone
    assert ">MCP 地址<" not in resp.text
