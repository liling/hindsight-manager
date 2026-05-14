import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.auth.dependencies import get_current_user


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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("hindsight_manager.api.auth.create_otp", return_value="test-otp-token")
async def test_otp_returns_clean_redirect_url(mock_create_otp, client: AsyncClient):
    mock_membership = MagicMock()
    mock_membership_result = MagicMock()
    mock_membership_result.scalar_one_or_none.return_value = mock_membership

    mock_tenant = MagicMock()
    mock_tenant.schema_name = "tenant_abc12345"
    mock_tenant_result = MagicMock()
    mock_tenant_result.scalar_one_or_none.return_value = mock_tenant

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [mock_membership_result, mock_tenant_result]

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.post(
        "/auth/otp?tenant_id=00000000-0000-0000-0000-000000000001",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "redirect_url" in data
    assert "tenant_abc12345" in data["redirect_url"]
    assert "test-otp-token" not in data["redirect_url"]
    assert data["redirect_url"].startswith("http://tenant_abc12345.cp.local.mem99.cn:9996")


@pytest.mark.asyncio
async def test_otp_redirect_form_returns_html(client: AsyncClient):
    resp = await client.get(
        "/auth/otp/redirect?otp=test-otp&cp_url=http://example.com/api/auth/sso",
    )
    assert resp.status_code == 200
    assert 'method="POST"' in resp.text
    assert 'action="http://example.com/api/auth/sso"' in resp.text
    assert 'value="test-otp"' in resp.text