import uuid
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from hindsight_manager.auth.dependencies import get_current_user, require_admin
from hindsight_manager.auth.session import create_access_token
from hindsight_manager.config import Settings


def _app():
    app = FastAPI()

    @app.get("/me")
    async def me(user=Depends(get_current_user)):
        return user

    @app.get("/admin")
    async def admin(user=Depends(require_admin)):
        return user

    return app


def _token(role: str = "admin", client_id: str = "hm-prod"):
    s = Settings()
    return create_access_token(
        user_id=str(uuid.uuid4()),
        tenant_id="test-tenant",
        secret=s.jwt_secret,
        # Note: HM's create_access_token signs a data-plane token (no aud/iss),
        # not a session JWT. For session JWT verification we use decode_access_token
        # which expects xinyi-platform format. Build a compatible token directly:
    )


def _session_token(role: str = "admin", client_id: str = "hm-prod"):
    """Build a xinyi-platform-format JWT that HM's decode_access_token will accept."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    s = Settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "xinyi-platform",
        "sub": str(uuid.uuid4()),
        "aud": client_id,
        "username": "alice",
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=900)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def test_get_current_user_no_cookie_returns_401():
    client = TestClient(_app())
    assert client.get("/me").status_code == 401


def test_get_current_user_garbage_cookie_returns_401():
    client = TestClient(_app())
    assert client.get("/me", cookies={"hindsight_session": "garbage"}).status_code == 401


def test_get_current_user_returns_dict():
    client = TestClient(_app())
    response = client.get("/me", cookies={"hindsight_session": _session_token()})
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"id", "username", "role"}
    assert body["username"] == "alice"
    assert body["role"] == "admin"


def test_get_current_user_wrong_audience_returns_401():
    client = TestClient(_app())
    response = client.get("/me", cookies={"hindsight_session": _session_token(client_id="other-client")})
    assert response.status_code == 401


def test_require_admin_non_admin_returns_403():
    client = TestClient(_app())
    response = client.get("/admin", cookies={"hindsight_session": _session_token(role="user")})
    assert response.status_code == 403
