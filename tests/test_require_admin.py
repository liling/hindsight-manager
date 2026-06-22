import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.config import Settings
from fastapi import HTTPException
import pytest


def _session_token(role: str = "admin"):
    s = Settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "xinyi-platform",
        "sub": str(uuid.uuid4()),
        "aud": "hm-prod",
        "username": "alice",
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=900)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    user = {"id": str(uuid.uuid4()), "username": "alice", "role": "admin"}
    result = await require_admin(user)
    assert result["role"] == "admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_user():
    user = {"id": str(uuid.uuid4()), "username": "alice", "role": "user"}
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user)
    assert exc_info.value.status_code == 403
