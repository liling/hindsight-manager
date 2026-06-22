import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hindsight_manager.platform.client import XinyiPlatformClient
from hindsight_manager.platform.config import PlatformSettings


@pytest.fixture
def settings():
    return PlatformSettings(
        platform_url="http://xinyi-test:8000",
        oauth_client_id="hm-prod",
        oauth_client_secret="test-secret",
        oauth_redirect_uri="http://hm:8001/auth/callback",
    )


async def test_batch_get_users_returns_dict(settings):
    user_id = uuid.uuid4()
    fake_response = {
        "users": {
            str(user_id): {"id": str(user_id), "username": "alice", "display_name": "Alice",
                           "email": None, "role": "admin", "is_active": True}
        }
    }
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value=fake_response):
        result = await client.batch_get_users([user_id])
    assert result[user_id]["username"] == "alice"


async def test_batch_get_users_handles_null_entries(settings):
    user_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    fake_response = {
        "users": {
            str(user_id): {"id": str(user_id), "username": "alice"},
            str(missing_id): None,
        }
    }
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value=fake_response):
        result = await client.batch_get_users([user_id, missing_id])
    assert result[user_id]["username"] == "alice"
    assert result.get(missing_id) is None


async def test_push_audit_never_raises(settings):
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, side_effect=Exception("network down")):
        await client.push_audit({
            "user_id": str(uuid.uuid4()),
            "action": "hm.test.event",
            "resource_type": "test",
            "resource_id": "1",
            "detail": {},
            "ip_address": None,
        })


async def test_refresh_token_returns_payload_on_success(settings):
    expected = {"access_token": "abc", "refresh_token": "def", "expires_in": 900}
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value=expected):
        result = await client.refresh_token("raw-old-refresh")
    assert result == expected


async def test_refresh_token_returns_none_on_error(settings):
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value=None):
        result = await client.refresh_token("bad-token")
    assert result is None


async def test_exchange_oauth_code_returns_payload(settings):
    expected = {"access_token": "a", "refresh_token": "r", "expires_in": 900, "user": {"id": "u"}}
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value=expected):
        result = await client.exchange_oauth_code(code="c", redirect_uri="http://hm/cb")
    assert result == expected


async def test_check_revocation_returns_bool(settings):
    client = XinyiPlatformClient(settings)
    with patch.object(client, "_post_json", new_callable=AsyncMock, return_value={"revoked": True}):
        result = await client.check_revocation(uuid.uuid4())
    assert result is True
