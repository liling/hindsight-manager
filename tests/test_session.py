from datetime import timedelta

from hindsight_manager.auth.session import create_token, decode_token


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
