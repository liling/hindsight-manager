import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app
from hindsight_manager.db import get_session


@pytest.fixture
async def client():
    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("hindsight_manager.api.auth.verify_password", return_value=False)
async def test_form_login_invalid_credentials(mock_verify, client: AsyncClient):
    # The default mock session's execute returns an AsyncMock, whose
    # scalar_one_or_none returns another AsyncMock (truthy). We need it
    # to return None so that the code hits the "user not found" branch.
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.post(
        "/auth/login/form",
        data={"username": "nonexistent", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "用户名或密码错误" in resp.text


@pytest.mark.asyncio
@patch("hindsight_manager.api.auth.verify_password", return_value=True)
async def test_form_login_success(mock_verify, client: AsyncClient):
    mock_user = MagicMock()
    mock_user.id = MagicMock()
    mock_user.id.__str__ = lambda self: "user-123"
    mock_user.username = "testuser"
    mock_user.password_hash = "hashed"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.post(
        "/auth/login/form",
        data={"username": "testuser", "password": "correct"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/dashboard" in resp.headers["location"]
    assert "hindsight_session" in resp.headers.get("set-cookie", "")
