from hindsight_manager.auth.session import (
    create_access_token,
    create_otp,
    exchange_otp,
    verify_access_token,
)

SECRET = "test-secret-with-at-least-32-characters!!"
TENANT = "tenant-uuid-1"


def test_create_and_verify_access_token():
    token = create_access_token("user-1", TENANT, SECRET)
    payload = verify_access_token(token, SECRET, TENANT)
    assert payload is not None
    assert payload["sub"] == "user-1"
    assert payload["tid"] == TENANT
    assert payload["type"] == "access"


def test_verify_access_token_wrong_tenant_returns_none():
    token = create_access_token("user-1", TENANT, SECRET)
    assert verify_access_token(token, SECRET, "other-tenant") is None


def test_verify_access_token_wrong_secret_returns_none():
    token = create_access_token("user-1", TENANT, SECRET)
    assert verify_access_token(token, "wrong-secret", TENANT) is None


def test_verify_access_token_invalid_jwt():
    assert verify_access_token("garbage", SECRET, TENANT) is None


def test_create_and_exchange_otp():
    otp = create_otp("user-1", TENANT)
    claims = exchange_otp(otp)
    assert claims is not None
    assert claims["user_id"] == "user-1"
    assert claims["tenant_id"] == TENANT


def test_exchange_otp_twice_returns_none():
    otp = create_otp("user-1", TENANT)
    assert exchange_otp(otp) is not None
    assert exchange_otp(otp) is None


def test_exchange_invalid_otp_returns_none():
    assert exchange_otp("nonexistent-otp") is None
