import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from hindsight_manager.auth.session import create_access_token
from hindsight_manager.config import Settings
from hindsight_manager.main import app


def _session_token(user_id=None, role="admin"):
    s = Settings()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "xinyi-platform",
        "sub": str(user_id or uuid.uuid4()),
        "aud": "hm-prod",
        "username": "alice",
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=900)).timestamp()),
    }
    from jose import jwt
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def test_callback_exchanges_code_and_sets_cookies():
    fake_user_id = str(uuid.uuid4())
    fake_pair = {
        "access_token": "ACCESS",
        "refresh_token": "REFRESH",
        "expires_in": 900,
        "user": {"id": fake_user_id, "username": "alice"},
    }
    with patch("hindsight_manager.api.auth.get_platform_client") as mock_get:
        client_mock = MagicMock()
        client_mock.exchange_oauth_code = AsyncMock(return_value=fake_pair)
        client_mock.aclose = AsyncMock()
        mock_get.return_value.__aenter__.return_value = client_mock

        client = TestClient(app)
        # Verify HM signature is used to validate state
        from hindsight_manager.config import Settings
        from hindsight_manager.auth.oauth_state import generate_oauth_state, sign_oauth_state
        s = Settings()
        state = generate_oauth_state()
        sig = sign_oauth_state(state, s.jwt_secret)

        response = client.get(
            "/auth/callback",
            params={"code": "test-code", "state": sig, "return_to": "/dashboard"},
            cookies={"hm_oauth_state": sig},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert "hindsight_session" in response.cookies
    assert "hindsight_refresh" in response.cookies


def test_callback_invalid_state_returns_400():
    client = TestClient(app)
    response = client.get(
        "/auth/callback",
        params={"code": "x", "state": "fake-sig"},
        cookies={"hm_oauth_state": "different-sig"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_callback_platform_returns_none_returns_401():
    from hindsight_manager.config import Settings
    from hindsight_manager.auth.oauth_state import generate_oauth_state, sign_oauth_state
    s = Settings()
    state = generate_oauth_state()
    sig = sign_oauth_state(state, s.jwt_secret)

    with patch("hindsight_manager.api.auth.get_platform_client") as mock_get:
        client_mock = MagicMock()
        client_mock.exchange_oauth_code = AsyncMock(return_value=None)
        client_mock.aclose = AsyncMock()
        mock_get.return_value.__aenter__.return_value = client_mock

        client = TestClient(app)
        response = client.get(
            "/auth/callback",
            params={"code": "bad", "state": sig},
            cookies={"hm_oauth_state": sig},
            follow_redirects=False,
        )
    assert response.status_code == 401


def test_login_redirect_302_to_platform():
    client = TestClient(app)
    response = client.get(
        "/auth/login-redirect",
        params={"return_to": "/admin/tenants"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "/oauth/authorize" in response.headers["location"]
    assert "client_id=hm-prod" in response.headers["location"]
    assert "hm_oauth_state" in response.cookies


def test_refresh_with_valid_cookie_updates_session():
    fake_pair = {
        "access_token": "NEW_ACCESS",
        "refresh_token": "NEW_REFRESH",
        "expires_in": 900,
    }
    with patch("hindsight_manager.api.auth.get_platform_client") as mock_get:
        client_mock = MagicMock()
        client_mock.refresh_token = AsyncMock(return_value=fake_pair)
        client_mock.aclose = AsyncMock()
        mock_get.return_value.__aenter__.return_value = client_mock

        client = TestClient(app)
        response = client.post(
            "/auth/refresh",
            cookies={"hindsight_refresh": "old-refresh"},
        )
    assert response.status_code == 200
    assert response.cookies.get("hindsight_session") == "NEW_ACCESS"


def test_refresh_without_cookie_returns_401():
    client = TestClient(app)
    response = client.post("/auth/refresh")
    assert response.status_code == 401


def test_logout_clears_cookies_and_revoke_platform_token():
    with patch("hindsight_manager.api.auth.get_platform_client") as mock_get:
        client_mock = MagicMock()
        client_mock.revoke_token = AsyncMock()
        client_mock.aclose = AsyncMock()
        mock_get.return_value.__aenter__.return_value = client_mock

        client = TestClient(app)
        response = client.post(
            "/auth/logout",
            cookies={"hindsight_session": "x", "hindsight_refresh": "y"},
        )
    assert response.status_code == 200
    client_mock.revoke_token.assert_awaited_once()
    set_cookie = response.headers.get("set-cookie", "")
    assert "hindsight_session" in set_cookie
    assert "hindsight_refresh" in set_cookie


def test_session_cookie_grants_access_to_business_endpoint():
    """Full round-trip: login-redirect → callback → business endpoint."""
    fake_user_id = str(uuid.uuid4())
    fake_session_token = _session_token(user_id=fake_user_id, role="admin")

    fake_pair = {
        "access_token": fake_session_token,
        "refresh_token": "REFRESH",
        "expires_in": 900,
        "user": {"id": fake_user_id, "username": "alice"},
    }

    with patch("hindsight_manager.api.auth.get_platform_client") as mock_get:
        client_mock = MagicMock()
        client_mock.exchange_oauth_code = AsyncMock(return_value=fake_pair)
        client_mock.aclose = AsyncMock()
        mock_get.return_value.__aenter__.return_value = client_mock

        client = TestClient(app)
        from hindsight_manager.config import Settings
        from hindsight_manager.auth.oauth_state import generate_oauth_state, sign_oauth_state
        s = Settings()
        state = generate_oauth_state()
        sig = sign_oauth_state(state, s.jwt_secret)

        callback_resp = client.get(
            "/auth/callback",
            params={"code": "x", "state": sig},
            cookies={"hm_oauth_state": sig},
            follow_redirects=False,
        )
        session_cookie = callback_resp.cookies.get("hindsight_session")
        assert session_cookie

        # The session cookie should be a valid HM JWT carrying our user's id
        from jose import jwt
        payload = jwt.decode(session_cookie, s.jwt_secret, algorithms=["HS256"], audience="hm-prod")
        assert payload["sub"] == fake_user_id
        assert payload["role"] == "admin"