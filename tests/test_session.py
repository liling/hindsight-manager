from datetime import timedelta

from jose import jwt

from hindsight_manager.auth.session import (
    create_access_token,
    create_token,
    decode_token,
    verify_access_token,
)


def test_create_and_decode_token():
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    username = "alice"
    token = create_token(user_id, username, secret="test-secret")
    payload = decode_token(token, secret="test-secret")
    assert payload["sub"] == user_id
    assert payload["username"] == username


def test_decode_expired_token():
    token = create_token("u1", "alice", secret="test-secret", expires_delta=timedelta(seconds=-1))
    assert decode_token(token, secret="test-secret") is None


def test_decode_wrong_secret():
    token = create_token("u1", "alice", secret="secret-a")
    assert decode_token(token, secret="secret-b") is None


def test_create_access_token_contains_claims():
    secret = "test-secret"
    token = create_access_token(user_id="user-123", tenant_id="tenant-456", secret=secret)
    payload = decode_token(token, secret)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["tid"] == "tenant-456"
    assert payload["type"] == "access"
    assert "exp" in payload


def test_verify_access_token_valid():
    secret = "test-secret"
    token = create_access_token(user_id="user-123", tenant_id="tenant-456", secret=secret)
    payload = verify_access_token(token, secret, "tenant-456")
    assert payload is not None
    assert payload["tid"] == "tenant-456"


def test_verify_access_token_wrong_tenant():
    secret = "test-secret"
    token = create_access_token(user_id="user-123", tenant_id="tenant-456", secret=secret)
    payload = verify_access_token(token, secret, "tenant-999")
    assert payload is None


def test_verify_access_token_expired():
    secret = "test-secret"
    from datetime import datetime, timezone

    expired_token = jwt.encode(
        {
            "sub": "user-123",
            "tid": "tenant-456",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        secret,
        algorithm="HS256",
    )
    payload = verify_access_token(expired_token, secret, "tenant-456")
    assert payload is None


def test_verify_access_token_wrong_type():
    secret = "test-secret"
    session_token = create_token(user_id="user-123", username="testuser", secret=secret)
    payload = verify_access_token(session_token, secret, "some-tenant")
    assert payload is None


def test_verify_access_token_invalid_jwt():
    payload = verify_access_token("garbage-token", "secret", "tenant-456")
    assert payload is None
