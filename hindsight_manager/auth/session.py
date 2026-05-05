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
