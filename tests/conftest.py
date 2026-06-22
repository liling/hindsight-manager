import os

# Set required env vars before any test module imports the app.
# Settings() is called at module level in proxy.py, so these must be
# available before `from hindsight_manager.main import app`.
os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret-for-manager")
os.environ.setdefault("HINDSIGHT_MANAGER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")


# ─── Test helpers (after Plan B dict refactor) ───

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock


def login_as(user_id: str, role: str = "user", username: str = "alice"):
    """Override get_current_user to return a dict user."""
    from hindsight_manager.auth.dependencies import get_current_user
    from hindsight_manager.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id, "username": username, "role": role,
    }


def clear_overrides():
    from hindsight_manager.main import app
    app.dependency_overrides.clear()


def mock_session_with_side_effect(side_effects):
    """Install a mock AsyncSession whose .execute returns results from side_effects (list)."""
    mock = AsyncMock()
    mock.execute.side_effect = side_effects
    mock.commit = AsyncMock()
    mock.delete = AsyncMock()
    mock.add = MagicMock()
    mock.get = AsyncMock(return_value=None)
    from hindsight_manager.db import get_session
    from hindsight_manager.main import app

    async def _override():
        yield mock

    app.dependency_overrides[get_session] = _override
    return mock


def patch_platform_client(*, batch_get_users=None, get_user_by_username=None):
    """Patch the XinyiPlatformClient to avoid real HTTP calls.

    Returns (patches_list, client_mock) — call p.stop() on each patch.
    """
    from unittest.mock import patch
    client_mock = MagicMock()
    client_mock.batch_get_users = AsyncMock(return_value=batch_get_users or {})
    client_mock.get_user_by_username = AsyncMock(return_value=get_user_by_username)
    client_mock.aclose = AsyncMock()

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield client_mock

    class FakePlatformClient:
        def __init__(self, *args, **kwargs):
            pass

        async def aclose(self):
            pass

    patches = [
        patch("hindsight_manager.api.members.XinyiPlatformClient", FakePlatformClient),
        patch("hindsight_manager.api.members._platform_client", _cm),
    ]
    return patches, client_mock


def platform_user_info(user_id, username="alice", role="user", **extras):
    """Build a fake user dict that XinyiPlatformClient would return."""
    base = {
        "id": user_id,
        "username": username,
        "display_name": username.title(),
        "email": None,
        "role": role,
        "is_active": True,
    }
    base.update(extras)
    return base