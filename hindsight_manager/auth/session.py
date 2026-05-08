import secrets
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


OTP_EXPIRE_SECONDS = 60

# In-memory OTP store. Key: OTP string, Value: {"user_id": str, "tenant_id": str, "expires": datetime}
_otp_store: dict[str, dict] = {}


def create_otp(user_id: str, tenant_id: str) -> str:
    _cleanup_expired_otps()
    otp = secrets.token_urlsafe(32)
    expire = datetime.now(timezone.utc) + timedelta(seconds=OTP_EXPIRE_SECONDS)
    _otp_store[otp] = {"user_id": user_id, "tenant_id": tenant_id, "expires": expire}
    return otp


def exchange_otp(otp: str) -> dict | None:
    _cleanup_expired_otps()
    entry = _otp_store.pop(otp, None)
    if entry is None:
        return None
    if datetime.now(timezone.utc) > entry["expires"]:
        return None
    return {"user_id": entry["user_id"], "tenant_id": entry["tenant_id"]}


def _cleanup_expired_otps() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _otp_store.items() if now > v["expires"]]
    for k in expired:
        del _otp_store[k]
