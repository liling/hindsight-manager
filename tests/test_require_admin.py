import os
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.models.user import UserRole


def _make_user(role: UserRole = UserRole.USER):
    u = MagicMock()
    u.role = role
    return u


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    admin = _make_user(UserRole.ADMIN)
    result = await require_admin(admin)
    assert result.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_require_admin_rejects_user():
    user = _make_user(UserRole.USER)
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user)
    assert exc_info.value.status_code == 403
