from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

TOKEN_EXPIRE_HOURS = 24


def create_token(
    user_id: str,
    username: str,
    secret: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=TOKEN_EXPIRE_HOURS))
    return jwt.encode(
        {"sub": user_id, "username": username, "exp": expire},
        secret,
        algorithm="HS256",
    )


def decode_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None


ACCESS_TOKEN_EXPIRE_MINUTES = 15


def create_access_token(user_id: str, tenant_id: str, secret: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "tid": tenant_id, "exp": expire, "type": "access"},
        secret,
        algorithm="HS256",
    )


def verify_access_token(token: str, secret: str, tenant_id: str) -> dict | None:
    payload = decode_token(token, secret)
    if payload is None:
        return None
    if payload.get("type") != "access":
        return None
    if payload.get("tid") != tenant_id:
        return None
    return payload
