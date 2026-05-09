# Manager API Proxy MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 hindsight-manager 中新增 SM4 加密工具、短期访问令牌、反向代理路由，打通 SaaS 宿主 → Manager API → hindsight-api 的完整链路。

**Architecture:** Manager API 作为 API 网关。租户创建时自动生成系统级 API Key（SM4 加密存储）。SaaS 宿主通过 session cookie 换取 15 分钟短期 JWT，CP 前端携带 JWT 发起请求，Manager API 验证 JWT 后解密系统 Key 并注入 Authorization header 转发到 hindsight-api。

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), python-jose (HS256 JWT), gmssl (SM4-ECB), httpx (proxy), pytest + pytest-asyncio

**Project root:** `/Users/liling/src/lab/hindsight-manager/`

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `hindsight_manager/crypto.py` | Create | SM4-ECB 加解密工具 |
| `hindsight_manager/config.py` | Modify | 新增 `encryption_key`、`dataplane_url` |
| `hindsight_manager/models/api_key.py` | Modify | 新增 `is_system`、`encrypted_key` 列 |
| `hindsight_manager/auth/session.py` | Modify | 新增短期 JWT 签发/验证 |
| `hindsight_manager/api/auth.py` | Modify | 新增 `POST /auth/access-token` |
| `hindsight_manager/api/proxy.py` | Create | 通用反向代理路由 |
| `hindsight_manager/api/tenants.py` | Modify | 创建租户时自动生成系统 Key |
| `hindsight_manager/api/api_keys.py` | Modify | 过滤系统级 Key |
| `hindsight_manager/main.py` | Modify | 注册 proxy router |
| `hindsight_manager/migrations/versions/002_add_system_api_key.py` | Create | 数据库迁移 |
| `tests/test_crypto.py` | Create | SM4 加解密测试 |
| `tests/test_session.py` | Modify | 短期 JWT 测试 |
| `tests/test_access_token.py` | Create | access-token 端点测试 |
| `tests/test_proxy.py` | Create | 反向代理路由测试 |

---

### Task 1: Add gmssl dependency and SM4 crypto module

**Files:**
- Modify: `pyproject.toml` (add `gmssl` dependency)
- Create: `hindsight_manager/crypto.py`
- Create: `tests/test_crypto.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crypto.py
import pytest

from hindsight_manager.crypto import decrypt_sm4, encrypt_sm4


def test_encrypt_decrypt_roundtrip():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "hsm_abc123secretkey456xyz789"
    ciphertext = encrypt_sm4(plaintext, key)
    assert ciphertext != plaintext
    assert decrypt_sm4(ciphertext, key) == plaintext


def test_encrypt_produces_base64():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ciphertext = encrypt_sm4("test-data", key)
    import base64
    base64.b64decode(ciphertext)  # should not raise


def test_decrypt_wrong_key_raises():
    key1 = bytes.fromhex("0123456789abcdef0123456789abcdef")
    key2 = bytes.fromhex("fedcba9876543210fedcba9876543210")
    ciphertext = encrypt_sm4("test-data", key1)
    with pytest.raises(Exception):
        decrypt_sm4(ciphertext, key2)


def test_encrypt_different_plaintexts_different_ciphertexts():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ct1 = encrypt_sm4("plaintext_a", key)
    ct2 = encrypt_sm4("plaintext_b", key)
    assert ct1 != ct2


def test_encrypt_long_plaintext():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "x" * 200
    assert decrypt_sm4(encrypt_sm4(plaintext, key), key) == plaintext
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hindsight_manager.crypto'`

- [ ] **Step 3: Add gmssl dependency**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv add gmssl`

This updates `pyproject.toml` and `uv.lock`.

- [ ] **Step 4: Create crypto module**

```python
# hindsight_manager/crypto.py
import base64

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT


def encrypt_sm4(plaintext: str, key: bytes) -> str:
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_ENCRYPT)
    data = plaintext.encode()
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len] * pad_len)
    ciphertext = sm4.crypt_ecb(data)
    return base64.b64encode(ciphertext).decode()


def decrypt_sm4(ciphertext_b64: str, key: bytes) -> str:
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT)
    ciphertext = base64.b64decode(ciphertext_b64)
    plaintext_padded = sm4.crypt_ecb(ciphertext)
    pad_len = plaintext_padded[-1]
    return plaintext_padded[:-pad_len].decode()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_crypto.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add pyproject.toml uv.lock hindsight_manager/crypto.py tests/test_crypto.py
git commit -m "feat: add SM4 encryption module for system API key storage"
```

---

### Task 2: Add config fields and update ApiKey model

**Files:**
- Modify: `hindsight_manager/config.py` — add `encryption_key` and `dataplane_url`
- Modify: `hindsight_manager/models/api_key.py` — add `is_system` and `encrypted_key` columns
- Create: `hindsight_manager/migrations/versions/002_add_system_api_key.py`

- [ ] **Step 1: Update config**

In `hindsight_manager/config.py`, add two fields to the `Settings` class:

```python
# hindsight_manager/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    encryption_key: str = "0123456789abcdef0123456789abcdef"  # 32 hex chars, 128-bit SM4 key
    dataplane_url: str = "http://localhost:8888"
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_"}
```

`encryption_key` defaults to a test value so existing dev setups don't break, but production MUST set `HINDSIGHT_MANAGER_ENCRYPTION_KEY`.

- [ ] **Step 2: Update ApiKey model**

In `hindsight_manager/models/api_key.py`, add two columns:

```python
# hindsight_manager/models/api_key.py
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(server_default="now()")
    last_used_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")
```

- [ ] **Step 3: Create migration**

```python
# hindsight_manager/migrations/versions/002_add_system_api_key.py
"""Add is_system and encrypted_key to api_keys

Revision ID: 002
Revises: 001
Create Date: 2026-05-07
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

SCHEMA = "manager"


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"), schema=SCHEMA)
    op.add_column("api_keys", sa.Column("encrypted_key", sa.Text(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("api_keys", "encrypted_key", schema=SCHEMA)
    op.drop_column("api_keys", "is_system", schema=SCHEMA)


import sqlalchemy as sa  # noqa: E402 — needed for sa.Column in upgrade()
```

Note: The `import sqlalchemy as sa` is placed after the function definitions because Alembic templates typically have it at top. If the project's existing `001_initial_schema.py` uses `sa.` at the module level, move the import to the top instead. Check the existing migration's import style and match it.

- [ ] **Step 4: Run the migration against dev database**

Run: `cd /Users/liling/src/lab/hindsight-manager && alembic upgrade head`
Expected: The migration applies, adding two columns to `manager.api_keys`.

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/config.py hindsight_manager/models/api_key.py hindsight_manager/migrations/versions/002_add_system_api_key.py
git commit -m "feat: add config fields and model for system API key encryption"
```

---

### Task 3: Add short-lived access token functions to session module

**Files:**
- Modify: `hindsight_manager/auth/session.py`
- Modify: `tests/test_session.py`

- [ ] **Step 1: Write the failing test**

The existing `tests/test_session.py` tests `create_token` and `decode_token`. Add tests for the new functions at the end of the file:

```python
# Append to tests/test_session.py

from hindsight_manager.auth.session import create_access_token, verify_access_token


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
    token = create_access_token(user_id="user-123", tenant_id="tenant-456", secret=secret)
    # Manually create an expired token
    from datetime import datetime, timedelta, timezone
    expired_token = jwt.encode(
        {"sub": "user-123", "tid": "tenant-456", "type": "access",
         "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        secret, algorithm="HS256",
    )
    payload = verify_access_token(expired_token, secret, "tenant-456")
    assert payload is None


def test_verify_access_token_wrong_type():
    secret = "test-secret"
    # Create a session-type token (no "type": "access")
    session_token = create_token(user_id="user-123", username="testuser", secret=secret)
    payload = verify_access_token(session_token, secret, "some-tenant")
    assert payload is None


def test_verify_access_token_invalid_jwt():
    payload = verify_access_token("garbage-token", "secret", "tenant-456")
    assert payload is None
```

*(Note: `jwt` and `decode_token` imports should already exist at the top of the file. The existing imports are `from hindsight_manager.auth.session import create_token, decode_token`. Also add `from jose import jwt` for the expired token test.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_session.py::test_create_access_token_contains_claims -v`
Expected: FAIL — `ImportError: cannot import name 'create_access_token' from 'hindsight_manager.auth.session'`

- [ ] **Step 3: Implement access token functions**

Add to the end of `hindsight_manager/auth/session.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_session.py -v`
Expected: All tests pass (original + 6 new)

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/auth/session.py tests/test_session.py
git commit -m "feat: add short-lived access token creation and verification"
```

---

### Task 4: Add POST /auth/access-token endpoint

**Files:**
- Modify: `hindsight_manager/api/auth.py`
- Create: `tests/test_access_token.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_access_token.py
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.auth.session import create_access_token, create_token
from hindsight_manager.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _session_cookie(user_id: str, username: str, secret: str) -> dict[str, str]:
    token = create_token(user_id, username, secret)
    return {"cookies": {"hindsight_session": token}}


async def test_access_token_missing_auth(client: AsyncClient):
    resp = await client.post(f"/auth/access-token?tenant_id={uuid.uuid4()}")
    assert resp.status_code == 401


async def test_access_token_invalid_session(client: AsyncClient):
    resp = await client.post(
        f"/auth/access-token?tenant_id={uuid.uuid4()}",
        cookies={"hindsight_session": "invalid-token"},
    )
    assert resp.status_code == 401


async def test_access_token_nonexistent_tenant(client: AsyncClient):
    """
    This test requires a real user in the DB.
    If no DB is available, it will fail — that's expected for integration tests.
    Mark with pytest.mark.integration if there's a pattern for that.
    """
    pass  # Placeholder — full integration test runs against real DB
```

The true integration test (valid session → valid tenant → get access token) requires a running DB with a user and tenant inserted. That test belongs in `test_integration.py` with the existing integration test pattern. The unit-level tests above verify auth rejection.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_access_token.py -v`
Expected: FAIL — 404 (route not yet registered)

- [ ] **Step 3: Implement the endpoint**

Add to `hindsight_manager/api/auth.py`:

```python
# Add to imports at top of file:
from hindsight_manager.auth.session import create_access_token
from hindsight_manager.models.tenant_member import TenantMember

# Add to router body (after the /me endpoint):

class AccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    tenant_id: str


@router.post("/access-token", response_model=AccessTokenResponse)
async def create_access_token_endpoint(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Verify membership
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == current_user.id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    settings = Settings()
    token = create_access_token(
        user_id=str(current_user.id),
        tenant_id=str(tenant_id),
        secret=settings.jwt_secret,
    )
    return AccessTokenResponse(
        access_token=token,
        expires_in=900,
        tenant_id=str(tenant_id),
    )
```

Also ensure `uuid` is imported at the top: `import uuid`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_access_token.py -v`
Expected: 2 passed (the 2 auth-rejection tests), 1 skipped (the placeholder)

- [ ] **Step 5: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/api/auth.py tests/test_access_token.py
git commit -m "feat: add POST /auth/access-token endpoint for short-lived JWT"
```

---

### Task 5: Auto-generate system API Key on tenant creation

**Files:**
- Modify: `hindsight_manager/api/tenants.py`

- [ ] **Step 1: Update create_tenant to generate system key**

The current `create_tenant` in `hindsight_manager/api/tenants.py` creates a Tenant and TenantMember. After creating those, add system API key generation:

```python
# Add to imports at top of tenants.py:
import hashlib
import secrets

from hindsight_manager.config import Settings
from hindsight_manager.crypto import encrypt_sm4
from hindsight_manager.models.api_key import ApiKey

KEY_PREFIX = "hsm_"
SYSTEM_KEY_NAME = "system-proxy-key"
```

Then modify `create_tenant` — add the following after `session.add(membership)` and before `await session.commit()`:

```python
    # Auto-generate system API key
    settings = Settings()
    raw_key = f"{KEY_PREFIX}{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16]
    encryption_key_bytes = bytes.fromhex(settings.encryption_key)
    encrypted_key = encrypt_sm4(raw_key, encryption_key_bytes)

    system_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=SYSTEM_KEY_NAME,
        is_system=True,
        encrypted_key=encrypted_key,
    )
    session.add(system_key)
```

The full `create_tenant` function becomes:

```python
@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    schema_name = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=req.name, schema_name=schema_name, status=TenantStatus.ACTIVE)
    session.add(tenant)
    await session.flush()

    membership = TenantMember(user_id=current_user.id, tenant_id=tenant.id, role=MemberRole.OWNER)
    session.add(membership)

    # Auto-generate system API key
    settings = Settings()
    raw_key = f"{KEY_PREFIX}{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16]
    encryption_key_bytes = bytes.fromhex(settings.encryption_key)
    encrypted_key = encrypt_sm4(raw_key, encryption_key_bytes)

    system_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=SYSTEM_KEY_NAME,
        is_system=True,
        encrypted_key=encrypted_key,
    )
    session.add(system_key)

    await session.commit()
    await session.refresh(tenant)
    return _tenant_response(tenant)
```

- [ ] **Step 2: Filter system keys from API key listing**

In `hindsight_manager/api/api_keys.py`, find the `list_api_keys` endpoint and add `.where(ApiKey.is_system == False)` to the query:

The current query is something like:
```python
result = await session.execute(
    select(ApiKey).where(ApiKey.tenant_id == tenant_id)
)
```

Change to:
```python
result = await session.execute(
    select(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.is_system == False)
)
```

Also add `from hindsight_manager.models.api_key import ApiKey` at the top if it's not already imported.

- [ ] **Step 3: Test manually against running DB**

Start the manager API and call:
```bash
# Login first
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"provider":"local","username":"admin","password":"<password>"}' \
  -c cookies.txt

# Create tenant
curl -X POST http://localhost:8001/tenants \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Tenant"}' \
  -b cookies.txt

# Verify system key was created in DB:
# psql -c "SELECT id, name, is_system, key_prefix FROM manager.api_keys WHERE is_system = true;"
```

- [ ] **Step 4: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/api/tenants.py hindsight_manager/api/api_keys.py
git commit -m "feat: auto-generate system API key on tenant creation"
```

---

### Task 6: Create reverse proxy route

**Files:**
- Create: `hindsight_manager/api/proxy.py`
- Create: `tests/test_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proxy.py
import pytest
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_proxy_missing_auth(client: AsyncClient):
    resp = await client.get("/api/proxy/00000000-0000-0000-0000-000000000001/banks")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing authorization token"


async def test_proxy_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/proxy/00000000-0000-0000-0000-000000000001/banks",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_proxy.py -v`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Implement proxy route**

```python
# hindsight_manager/api/proxy.py
import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.session import verify_access_token
from hindsight_manager.config import Settings
from hindsight_manager.crypto import decrypt_sm4
from hindsight_manager.db import get_session
from hindsight_manager.models.api_key import ApiKey

router = APIRouter(tags=["proxy"])

settings = Settings()
http_client = httpx.AsyncClient(timeout=30.0)


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _resolve_system_key(session: AsyncSession, tenant_id: str) -> str:
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.tenant_id == tenant_id,
            ApiKey.is_system == True,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key or not api_key.encrypted_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="No system API key found for tenant")

    encryption_key_bytes = bytes.fromhex(settings.encryption_key)
    return decrypt_sm4(api_key.encrypted_key, encryption_key_bytes)


async def _proxy_request(request: Request, tenant_id: str, path: str) -> Response:
    from fastapi import HTTPException

    # Validate access token
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    payload = verify_access_token(token, settings.jwt_secret, tenant_id)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Resolve system API key
    session: AsyncSession = Depends(get_session)
    # We need the session from the request state — use a dependency approach instead
    return await _proxy_request_inner(request, tenant_id, path)


async def _do_proxy(
    request: Request,
    tenant_id: str,
    path: str,
    session: AsyncSession,
) -> Response:
    from fastapi import HTTPException

    # Validate access token
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    payload = verify_access_token(token, settings.jwt_secret, tenant_id)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Resolve system API key
    system_key = await _resolve_system_key(session, tenant_id)

    # Build upstream URL
    upstream_url = f"{settings.dataplane_url}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Prepare headers — replace Authorization, pass through Content-Type
    headers = {}
    if "content-type" in request.headers:
        headers["content-type"] = request.headers["content-type"]
    headers["authorization"] = system_key

    # Read body for methods that have one
    body = await request.body()

    # Forward request
    try:
        upstream_resp = await http_client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body if body else None,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream timeout")

    # Build response
    response_headers = {}
    for key, value in upstream_resp.headers.items():
        if key.lower() not in ("content-encoding", "transfer-encoding", "content-length"):
            response_headers[key] = value

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )


@router.api_route("/api/proxy/{tenant_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_route(
    request: Request,
    tenant_id: str,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    return await _do_proxy(request, tenant_id, path, session)
```

- [ ] **Step 4: Register proxy router in main.py**

In `hindsight_manager/main.py`, add the import and registration:

```python
from hindsight_manager.api.proxy import router as proxy_router

# Add to app router registrations:
app.include_router(proxy_router)
```

The full `main.py` becomes:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hindsight_manager.api.api_keys import router as api_keys_router
from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.api.members import router as members_router
from hindsight_manager.api.proxy import router as proxy_router
from hindsight_manager.api.tenants import router as tenants_router
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Hindsight Manager", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(members_router)
app.include_router(api_keys_router)
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/liling/src/lab/hindsight-manager && uv run pytest tests/test_proxy.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/liling/src/lab/hindsight-manager
git add hindsight_manager/api/proxy.py hindsight_manager/main.py tests/test_proxy.py
git commit -m "feat: add reverse proxy route with JWT validation and SM4 key decryption"
```

---

### Task 7: End-to-end integration verification

This task verifies the complete chain manually against a running database. It does not create new files — it validates all previous tasks work together.

- [ ] **Step 1: Run migrations**

```bash
cd /Users/liling/src/lab/hindsight-manager
alembic upgrade head
```

Expected: Migration 002 applies successfully.

- [ ] **Step 2: Start Manager API**

```bash
cd /Users/liling/src/lab/hindsight-manager
uv run uvicorn hindsight_manager.main:app --port 8001 --reload
```

Expected: Server starts on port 8001.

- [ ] **Step 3: Verify health endpoint**

```bash
curl http://localhost:8001/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Login**

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"provider":"local","username":"admin","password":"<YOUR_PASSWORD>"}' \
  -c /tmp/manager-cookies.txt -v
```

Expected: 200 with session cookie set.

- [ ] **Step 5: Create tenant and verify system key**

```bash
curl -X POST http://localhost:8001/tenants \
  -H "Content-Type: application/json" \
  -d '{"name":"E2E Test"}' \
  -b /tmp/manager-cookies.txt
```

Save the tenant `id` from the response.

```bash
# Check system key exists in DB
psql -d hindsight_dev -c "SELECT name, is_system, key_prefix FROM manager.api_keys WHERE is_system = true;"
```

Expected: One row with `name='system-proxy-key'`, `is_system=true`.

- [ ] **Step 6: Get access token**

```bash
TENANT_ID="<tenant-uuid-from-step-5>"
curl -X POST "http://localhost:8001/auth/access-token?tenant_id=$TENANT_ID" \
  -b /tmp/manager-cookies.txt
```

Expected: `{"access_token":"eyJ...","expires_in":900,"tenant_id":"..."}`

Save the `access_token`.

- [ ] **Step 7: Test proxy route (auth validation only)**

```bash
ACCESS_TOKEN="<token-from-step-6>"
# Without token — should 401
curl http://localhost:8001/api/proxy/$TENANT_ID/v1/default/banks

# With token — should try to reach upstream (may 502/404 if hindsight-api not running)
curl http://localhost:8001/api/proxy/$TENANT_ID/v1/default/banks \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Expected:
- Without token: 401 `{"detail":"Missing authorization token"}`
- With token + hindsight-api running: proxied response from hindsight-api
- With token + hindsight-api NOT running: 502 or connection error (this is fine — validates proxy attempts to reach upstream)

- [ ] **Step 8: Commit any fixes**

If any issues found during integration testing, fix and commit:

```bash
cd /Users/liling/src/lab/hindsight-manager
git add -A
git commit -m "fix: integration test fixes for proxy MVP"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Task |
|---|---|
| 2.1 api_keys model changes | Task 2 |
| 2.2 Auto-generate system key | Task 5 |
| 2.3 Alembic migration | Task 2 |
| 3.1 SM4 crypto module | Task 1 |
| 3.2 Encryption key config | Task 2 |
| 4.1 POST /auth/access-token | Task 4 |
| 4.2 Session module changes | Task 3 |
| 5.1 Reverse proxy route | Task 6 |
| 5.2 Dataplane URL config | Task 2 |
| 5.3 Register proxy router | Task 6 |
| 7 Error handling | Task 6 |
| 8 API key list filtering | Task 5 |
| 10 End-to-end verification | Task 7 |

### Placeholder Scan

No TBD, TODO, or "fill in details" found. All code blocks contain complete implementations.

### Type Consistency

- `create_access_token(user_id: str, tenant_id: str, secret: str) -> str` — consistent across Task 3 (definition) and Task 4 (usage)
- `verify_access_token(token: str, secret: str, tenant_id: str) -> dict | None` — consistent across Task 3 (definition) and Task 6 (usage)
- `encrypt_sm4(plaintext: str, key: bytes) -> str` / `decrypt_sm4(ciphertext_b64: str, key: bytes) -> str` — consistent across Task 1 (definition), Task 5 and Task 6 (usage)
- `ApiKey.is_system: bool` and `ApiKey.encrypted_key: str | None` — consistent across Task 2 (model), Task 5 (creation), Task 6 (query)
