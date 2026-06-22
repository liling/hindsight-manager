import hashlib
import hmac
import secrets


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def sign_oauth_state(state: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), state.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def verify_oauth_state(state: str, signature: str, secret: str) -> bool:
    expected = sign_oauth_state(state, secret)
    return hmac.compare_digest(expected, signature)
