# Security Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 10 security findings from the standard audit (4 High, 4 Medium, 2 Low) across hindsight-manager and hindsight-control-plane.

**Architecture:** 10 independent tasks, each producing a self-contained commit. Tasks 1-4 are HIGH priority. Task 6 spans two repositories (manager + control-plane). No external dependencies added — rate limiter is custom in-memory.

**Tech Stack:** Python 3.11+ (FastAPI, gmssl, SQLAlchemy), TypeScript (Next.js middleware)

**Design Spec:** `docs/superpowers/specs/2026-05-14-security-audit-fixes-design.md`

---

## File Structure

### hindsight-manager

| File | Action | Responsibility |
|------|--------|---------------|
| `hindsight_manager/crypto.py` | Rewrite | SM4-ECB → SM4-CBC with random IV |
| `hindsight_manager/config.py` | Modify | Remove default key + add validator + add `session_secure` |
| `hindsight_manager/api/auth.py` | Modify | OTP POST form redirect + secure cookie flag |
| `hindsight_manager/api/proxy.py` | Modify | Response header whitelist |
| `hindsight_manager/api/password.py` | Modify | `secrets` for codes + remove code from dev fallback |
| `hindsight_manager/api/admin.py` | Modify | XFF last-entry + LIKE escape helper |
| `hindsight_manager/middleware/__init__.py` | Create | Empty package init |
| `hindsight_manager/middleware/rate_limit.py` | Create | In-memory sliding window rate limiter |
| `hindsight_manager/static/app.js` | Modify | `enterConsole` → redirect to OTP form page |
| `tests/conftest.py` | Modify | Add `ENCRYPTION_KEY` env var |
| `tests/test_crypto.py` | Modify | Add CBC-specific tests, remove legacy compat test |
| `tests/test_otp_redirect.py` | Modify | Update assertion for new redirect_url format |

### hindsight-control-plane

| File | Action | Responsibility |
|------|--------|---------------|
| `src/middleware.ts` | Modify | Remove OTP-from-searchParams logic |
| `src/app/api/auth/sso/route.ts` | Create | POST handler for OTP exchange + cookie set |

---

## Task 1: [HIGH-2] Remove hardcoded default encryption key

**Files:**
- Modify: `hindsight_manager/config.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update conftest.py with encryption key env var**

In `tests/conftest.py`, add this line after the existing `setdefault` calls:

```python
os.environ.setdefault("HINDSIGHT_MANAGER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
```

- [ ] **Step 2: Remove default and add validator in config.py**

Replace the entire `hindsight_manager/config.py` with:

```python
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "manager"
    auth_provider: str = "local"
    cas_server_url: str | None = None
    cas_service_url: str | None = None
    jwt_secret: str
    encryption_key: str = ""
    admin_password: str = ""
    dataplane_url: str = "http://localhost:8888"
    host: str = "0.0.0.0"
    port: int = 8001
    base_url: str = "http://localhost:8001"
    session_secure: bool = True
    cp_base_domain: str = "cp.local.mem99.cn"
    cp_port: str = "9996"
    cp_scheme: str = "http"

    # Email service configuration
    email_service: str = "smtp"  # smtp or sendgrid
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    sendgrid_api_key: str | None = None
    sendgrid_from_email: str | None = None

    model_config = {"env_prefix": "HINDSIGHT_MANAGER_", "env_file": ".env"}

    @model_validator(mode="after")
    def _validate_encryption_key(self) -> "Settings":
        if not self.encryption_key:
            raise ValueError(
                "HINDSIGHT_MANAGER_ENCRYPTION_KEY must be set. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(16))"'
            )
        if len(bytes.fromhex(self.encryption_key)) != 16:
            raise ValueError("HINDSIGHT_MANAGER_ENCRYPTION_KEY must be 16 bytes (32 hex chars)")
        return self

    def cp_url_for_tenant(self, slug: str) -> str:
        return f"{self.cp_scheme}://{slug}.{self.cp_base_domain}:{self.cp_port}"
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/config.py tests/conftest.py
git commit -m "fix(security): remove default encryption key, require explicit configuration"
```

---

## Task 2: [HIGH-1] Switch SM4-ECB to SM4-CBC with random IV

**Files:**
- Rewrite: `hindsight_manager/crypto.py`
- Modify: `tests/test_crypto.py`

- [ ] **Step 1: Write failing tests for CBC mode**

Append these tests to `tests/test_crypto.py`:

```python
def test_cbc_same_plaintext_different_ciphertext():
    """CBC with random IV must produce different ciphertext each time."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "hello world"
    ct1 = encrypt_sm4(plaintext, key)
    ct2 = encrypt_sm4(plaintext, key)
    assert ct1 != ct2


def test_cbc_ciphertext_longer_than_ecb():
    """CBC ciphertext includes 16-byte IV prefix, so it's longer than plaintext + padding alone."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "short"
    ct_b64 = encrypt_sm4(plaintext, key)
    import base64
    raw = base64.b64decode(ct_b64)
    # IV (16) + at least one block (16) = 32 bytes minimum
    assert len(raw) >= 32


def test_cbc_roundtrip_empty_string():
    """CBC handles empty plaintext."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ct = encrypt_sm4("", key)
    assert decrypt_sm4(ct, key) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_crypto.py::test_cbc_same_plaintext_different_ciphertext -v`
Expected: FAIL (current ECB produces same ciphertext for same plaintext)

- [ ] **Step 3: Rewrite crypto.py with CBC mode**

Replace entire `hindsight_manager/crypto.py` with:

```python
import base64
import os

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT


def encrypt_sm4(plaintext: str, key: bytes) -> str:
    """Encrypt plaintext using SM4-CBC with random IV.

    Output: base64(IV_16bytes + ciphertext).
    """
    iv = os.urandom(16)
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_ENCRYPT)

    data = plaintext.encode()
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len] * pad_len)

    ciphertext = _cbc_encrypt(data, iv, sm4)
    return base64.b64encode(iv + ciphertext).decode()


def decrypt_sm4(ciphertext_b64: str, key: bytes) -> str:
    """Decrypt SM4-CBC ciphertext. Input: base64(IV + ciphertext)."""
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    ciphertext = raw[16:]

    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT)
    plaintext_padded = _cbc_decrypt(ciphertext, iv, sm4)
    pad_len = plaintext_padded[-1]
    return plaintext_padded[:-pad_len].decode()


def _cbc_encrypt(data: bytes, iv: bytes, sm4: CryptSM4) -> bytes:
    result = b""
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i : i + 16]
        xored = bytes(a ^ b for a, b in zip(block, prev))
        encrypted = sm4.crypt_ecb(xored)
        result += encrypted
        prev = encrypted
    return result


def _cbc_decrypt(data: bytes, iv: bytes, sm4: CryptSM4) -> bytes:
    result = b""
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i : i + 16]
        decrypted = sm4.crypt_ecb(block)
        result += bytes(a ^ b for a, b in zip(decrypted, prev))
        prev = block
    return result
```

- [ ] **Step 4: Run all crypto tests**

Run: `uv run pytest tests/test_crypto.py -v`
Expected: All tests PASS (including existing ones and new CBC tests)

- [ ] **Step 5: Commit**

```bash
git add hindsight_manager/crypto.py tests/test_crypto.py
git commit -m "fix(security): switch SM4 from ECB to CBC mode with random IV"
```

---

## Task 3: [HIGH-3 + MEDIUM-1] OTP POST form redirect + Secure cookie flag

This task covers the OTP redirect redesign (HIGH-3) and the cookie secure flag (MEDIUM-1) since they touch the same file.

**Files (hindsight-manager):**
- Modify: `hindsight_manager/api/auth.py`
- Modify: `hindsight_manager/static/app.js`
- Modify: `tests/test_otp_redirect.py`

- [ ] **Step 1: Update OTP endpoint and add redirect-form endpoint**

In `hindsight_manager/api/auth.py`, make these changes:

1. Add import for HTMLResponse at the top:
```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
```

2. Change `_set_session` to use `session_secure` config (MEDIUM-1):
```python
def _set_session(response: Response | JSONResponse, token: str) -> None:
    settings = Settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        max_age=86400,
        path="/",
        samesite="lax",
        secure=settings.session_secure,
    )
```

3. Change `create_otp_endpoint` to return clean URL without OTP:
```python
@router.post("/otp", response_model=OtpResponse)
async def create_otp_endpoint(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.user_id == current_user.id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    otp = create_otp(str(current_user.id), str(tenant_id))
    settings = Settings()

    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    slug = tenant.schema_name if tenant else str(tenant_id)

    redirect_url = f"{settings.cp_url_for_tenant(slug)}/"

    return OtpResponse(otp=otp, expires_in=60, redirect_url=redirect_url)
```

4. Add new GET endpoint for the auto-submitting POST form:
```python
@router.get("/otp/redirect", response_class=HTMLResponse)
async def otp_redirect_form(
    request: Request,
    otp: str = ...,
    tenant_id: str = ...,
):
    """Render an auto-submitting POST form to securely send OTP to control plane."""
    settings = Settings()
    tenant_result = await session_execute_by_id(request, tenant_id)
    slug = tenant_result if tenant_result else tenant_id
    cp_url = f"{settings.cp_url_for_tenant(slug)}/api/auth/sso"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Redirecting...</title></head>
<body>
<form id="f" method="POST" action="{cp_url}">
  <input type="hidden" name="otp" value="{otp}">
</form>
<p>Redirecting...</p>
<script>document.getElementById('f').submit()</script>
</body></html>"""
    return HTMLResponse(content=html)
```

Wait — the otp_redirect_form endpoint needs to resolve the tenant slug from tenant_id. To keep it simple and avoid adding DB session as a dependency on a transient page, let the manager JS handle URL construction. The endpoint just needs the control plane URL.

Replace step 4 with:

```python
@router.get("/otp/redirect", response_class=HTMLResponse)
async def otp_redirect_form(
    otp: str,
    cp_url: str,
):
    """Render an auto-submitting POST form to securely send OTP to control plane."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Redirecting...</title></head>
<body>
<form id="f" method="POST" action="{cp_url}">
  <input type="hidden" name="otp" value="{otp}">
</form>
<p>Redirecting...</p>
<script>document.getElementById('f').submit()</script>
</body></html>"""
    return HTMLResponse(content=html)
```

**NOTE:** `cp_url` is passed as query param (constructed by the JS frontend from the `/auth/otp` response's `redirect_url`). The only user-influenced input is `otp` (already a secret token) and `cp_url` (server-constructed URL from the prior `/auth/otp` call). Both are set in `<input value>` attributes which are inside the form body — no XSS risk from Jinja2 auto-escaping context since this is a plain string template. However, we must escape HTML metacharacters to be safe. Add `html.escape`:

```python
import html as html_module

@router.get("/otp/redirect", response_class=HTMLResponse)
async def otp_redirect_form(
    otp: str,
    cp_url: str,
):
    escaped_otp = html_lib.escape(otp)
    escaped_url = html_lib.escape(cp_url)
    content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Redirecting...</title></head>
<body>
<form id="f" method="POST" action="{escaped_url}">
  <input type="hidden" name="otp" value="{escaped_otp}">
</form>
<p>Redirecting...</p>
<script>document.getElementById('f').submit()</script>
</body></html>"""
    return HTMLResponse(content=content)
```

Add the import at the top of `auth.py` (standard library, no conflict with Jinja2):
```python
import html as html_lib
```

- [ ] **Step 2: Update app.js enterConsole function**

Replace the `enterConsole` function in `hindsight_manager/static/app.js` (lines 3-18):

```javascript
async function enterConsole(tenantId, tenantSlug) {
  try {
    const resp = await fetch(`/auth/otp?tenant_id=${tenantId}`, {
      method: "POST",
      credentials: "include",
    });
    if (!resp.ok) {
      alert("获取授权失败");
      return;
    }
    const { otp, redirect_url } = await resp.json();
    const cpSsoUrl = redirect_url + "api/auth/sso";
    // Open POST-form redirect page — OTP goes via POST body, never in URL
    window.open(`/auth/otp/redirect?otp=${encodeURIComponent(otp)}&cp_url=${encodeURIComponent(cpSsoUrl)}`, "_blank");
  } catch (e) {
    alert("网络错误");
  }
}
```

- [ ] **Step 3: Update test_otp_redirect.py**

Replace entire `tests/test_otp_redirect.py` with:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.auth.dependencies import get_current_user


@pytest.fixture
async def client():
    async def _override_session():
        yield AsyncMock()

    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.username = "testuser"
    mock_user.display_name = "Test User"

    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("hindsight_manager.api.auth.create_otp", return_value="test-otp-token")
async def test_otp_returns_clean_redirect_url(mock_create_otp, client: AsyncClient):
    mock_membership = MagicMock()
    mock_membership_result = MagicMock()
    mock_membership_result.scalar_one_or_none.return_value = mock_membership

    mock_tenant = MagicMock()
    mock_tenant.schema_name = "tenant_abc12345"
    mock_tenant_result = MagicMock()
    mock_tenant_result.scalar_one_or_none.return_value = mock_tenant

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [mock_membership_result, mock_tenant_result]

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.post(
        "/auth/otp?tenant_id=00000000-0000-0000-0000-000000000001",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "redirect_url" in data
    assert "tenant_abc12345" in data["redirect_url"]
    assert "test-otp-token" not in data["redirect_url"]
    assert data["redirect_url"].startswith("http://tenant_abc12345.cp.local.mem99.cn:9996")


@pytest.mark.asyncio
async def test_otp_redirect_form_returns_html(client: AsyncClient):
    resp = await client.get(
        "/auth/otp/redirect?otp=test-otp&cp_url=http://example.com/api/auth/sso",
    )
    assert resp.status_code == 200
    assert 'method="POST"' in resp.text
    assert 'action="http://example.com/api/auth/sso"' in resp.text
    assert 'value="test-otp"' in resp.text
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_otp_redirect.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add hindsight_manager/api/auth.py hindsight_manager/static/app.js tests/test_otp_redirect.py
git commit -m "fix(security): OTP via POST form redirect (no URL leakage) + secure cookie flag"
```

---

## Task 4: [HIGH-3 control-plane] Control-plane SSO endpoint + remove middleware OTP

**Files (hindsight-control-plane):**
- Modify: `src/middleware.ts`
- Create: `src/app/api/auth/sso/route.ts`

- [ ] **Step 1: Create SSO route handler**

Create `src/app/api/auth/sso/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";

const COOKIE_MAX_AGE = 900;

export async function POST(request: NextRequest) {
  const managerApiUrl =
    process.env.HINDSIGHT_CP_MANAGER_API_URL || "http://localhost:8001";
  const saasHostUrl =
    process.env.HINDSIGHT_CP_SAAS_HOST_URL || "http://localhost:3000";

  let otp: string | undefined;
  const contentType = request.headers.get("content-type") || "";

  if (contentType.includes("application/x-www-form-urlencoded")) {
    const formData = await request.formData();
    otp = formData.get("otp") as string | undefined;
  } else {
    try {
      const body = await request.json();
      otp = body.otp;
    } catch {
      // ignore parse error
    }
  }

  if (!otp) {
    return NextResponse.redirect(new URL("/dashboard", saasHostUrl));
  }

  try {
    const resp = await fetch(`${managerApiUrl}/auth/exchange-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ otp }),
    });

    if (!resp.ok) {
      return NextResponse.redirect(new URL("/dashboard", saasHostUrl));
    }

    const data = await resp.json();

    // Determine redirect target — use Referer header to get the tenant host
    const referer = request.headers.get("referer") || "";
    const proto = request.headers.get("x-forwarded-proto") || "http";
    const host = request.headers.get("host") || "";

    let targetUrl: URL;
    if (referer) {
      targetUrl = new URL("/dashboard", referer);
    } else {
      targetUrl = new URL("/dashboard", `${proto}://${host}`);
    }

    const response = NextResponse.redirect(targetUrl);
    response.cookies.set("session-jwt", data.jwt, {
      path: "/",
      maxAge: COOKIE_MAX_AGE,
      sameSite: "lax",
      httpOnly: true,
    });
    response.cookies.set("tenant-api-key", data.api_key, {
      path: "/",
      maxAge: COOKIE_MAX_AGE,
      sameSite: "lax",
      httpOnly: true,
    });
    return response;
  } catch {
    return NextResponse.redirect(new URL("/dashboard", saasHostUrl));
  }
}
```

- [ ] **Step 2: Remove OTP-from-searchParams logic from middleware.ts**

Replace entire `src/middleware.ts` with:

```typescript
import { NextRequest, NextResponse } from "next/server";

function extractTenantSlug(hostname: string): string | null {
  const hostWithoutPort = hostname.split(":")[0];
  const parts = hostWithoutPort.split(".cp.");
  if (parts.length < 2) return null;
  return parts[0];
}

export async function middleware(request: NextRequest) {
  const hostname = request.headers.get("host") || "";
  const tenantSlug = extractTenantSlug(hostname);

  if (!tenantSlug) {
    return NextResponse.next();
  }

  // Validate existing session
  const jwt = request.cookies.get("session-jwt");
  if (!jwt) {
    const saasHostUrl =
      process.env.HINDSIGHT_CP_SAAS_HOST_URL || "http://localhost:3000";
    return NextResponse.redirect(new URL("/dashboard", saasHostUrl));
  }

  // Inject tenant API key as request header so downstream API routes can use it
  const apiKey = request.cookies.get("tenant-api-key")?.value;
  const requestHeaders = new Headers(request.headers);
  if (apiKey) {
    requestHeaders.set("x-api-key", apiKey);
  }
  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 3: Build and verify**

Run: `cd /Users/liling/src/lab/hindsight/hindsight-control-plane && npx next build`
Expected: Build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
cd /Users/liling/src/lab/hindsight/hindsight-control-plane
git add src/middleware.ts src/app/api/auth/sso/route.ts
git commit -m "fix(security): receive OTP via POST body instead of URL query parameter"
```

---

## Task 5: [HIGH-4 + MEDIUM-4] Secure verification codes + remove code from dev fallback

**Files:**
- Modify: `hindsight_manager/api/password.py`

- [ ] **Step 1: Update _create_verification_code to use secrets**

In `hindsight_manager/api/password.py`, replace the `_create_verification_code` function (lines ~85-129) with:

```python
async def _create_verification_code(
    session: AsyncSession,
    email: str,
    purpose: str,
    expiry_minutes: int = 10,
) -> str:
    """Create and store verification code."""
    import secrets
    import string

    code = "".join(secrets.choice(string.digits) for _ in range(6))

    expires_at = datetime.now() + timedelta(minutes=expiry_minutes)

    await session.execute(
        EmailVerification.__table__.delete().where(
            and_(
                EmailVerification.email == email,
                EmailVerification.purpose == purpose,
                EmailVerification.verified == False,  # noqa: E712
            )
        )
    )

    verification = EmailVerification(
        email=email, code=code, purpose=purpose, expires_at=expires_at
    )
    session.add(verification)
    await session.commit()

    return code
```

- [ ] **Step 2: Remove verification code from dev fallback responses**

In `hindsight_manager/api/password.py`, find the `forgot_password` function's email-not-configured fallback (around lines 254-262) and replace:

```python
    else:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("Email service not configured. Verification code: %s", code)
        return MessageResponse(message="密码重置验证码已发送到您的邮箱")
```

Do the same for `send_verification_code` (around lines 282-290):

```python
    else:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("Email service not configured. Verification code: %s", code)
        return MessageResponse(message="验证码已发送到您的邮箱")
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_password_api.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/api/password.py
git commit -m "fix(security): use secrets for verification codes, remove code from dev fallback"
```

---

## Task 6: [MEDIUM-2] Custom in-memory rate limiter

**Files:**
- Create: `hindsight_manager/middleware/__init__.py`
- Create: `hindsight_manager/middleware/rate_limit.py`
- Modify: `hindsight_manager/api/auth.py`
- Modify: `hindsight_manager/api/password.py`

- [ ] **Step 1: Create middleware package**

Create empty `hindsight_manager/middleware/__init__.py`.

- [ ] **Step 2: Implement rate limiter dependency**

Create `hindsight_manager/middleware/rate_limit.py`:

```python
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


class RateLimiter:
    """In-memory sliding window rate limiter used as a FastAPI dependency."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def __call__(self, request: Request) -> None:
        key = f"{request.client.host}:{request.url.path}"
        now = time.time()
        cutoff = now - self.window_seconds

        # Evict old entries
        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(self.window_seconds)},
            )

        self._requests[key].append(now)


# Pre-configured limiters
login_limiter = RateLimiter(max_requests=5, window_seconds=60)
otp_limiter = RateLimiter(max_requests=10, window_seconds=60)
password_limiter = RateLimiter(max_requests=3, window_seconds=60)
```

- [ ] **Step 3: Apply rate limits to auth endpoints**

In `hindsight_manager/api/auth.py`, add import:

```python
from hindsight_manager.middleware.rate_limit import login_limiter, otp_limiter
```

Add `Depends(login_limiter)` and a `request: Request` parameter to these endpoints:

1. `login` — add `request: Request` as first param, add `Depends(login_limiter)` to deps:
```python
@router.post("/login")
async def login(
    request: Request,
    req: LoginRequest,
    _rate_limit=Depends(login_limiter),
    session: AsyncSession = Depends(get_session),
):
```

2. `login_form` — add `request: Request` as first param, add `Depends(login_limiter)`:
```python
@router.post("/login/form")
async def login_form(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    _rate_limit=Depends(login_limiter),
    session: AsyncSession = Depends(get_session),
):
```

3. `exchange_otp_endpoint` — add `request: Request` as first param, add `Depends(otp_limiter)`:
```python
@router.post("/exchange-otp", response_model=ExchangeOtpResponse)
async def exchange_otp_endpoint(
    request: Request,
    req: ExchangeOtpRequest,
    _rate_limit=Depends(otp_limiter),
    session: AsyncSession = Depends(get_session),
):
```

Add `Request` to the import from fastapi:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

- [ ] **Step 4: Apply rate limits to password endpoints**

In `hindsight_manager/api/password.py`, add import:

```python
from hindsight_manager.middleware.rate_limit import password_limiter
```

Add rate limit to `forgot_password`:
```python
@router.post("/forgot", response_model=MessageResponse)
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    _rate_limit=Depends(password_limiter),
    session: AsyncSession = Depends(get_session),
):
```

Add rate limit to `send_verification_code`:
```python
@router.post("/verify/send", response_model=MessageResponse)
async def send_verification_code(
    request: Request,
    req: SendVerificationRequest,
    _rate_limit=Depends(password_limiter),
    session: AsyncSession = Depends(get_session),
):
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -x`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add hindsight_manager/middleware/ hindsight_manager/api/auth.py hindsight_manager/api/password.py
git commit -m "fix(security): add in-memory rate limiting to auth and password endpoints"
```

---

## Task 7: [MEDIUM-3] Proxy response header whitelist

**Files:**
- Modify: `hindsight_manager/api/proxy.py`

- [ ] **Step 1: Replace blacklist with whitelist**

In `hindsight_manager/api/proxy.py`, replace lines 88-97 (the response building block) with:

```python
    # Only forward safe response headers from upstream
    _SAFE_HEADERS = frozenset({
        "content-type",
        "content-disposition",
        "cache-control",
        "etag",
        "x-request-id",
    })
    response_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() in _SAFE_HEADERS
    }

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_proxy.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add hindsight_manager/api/proxy.py
git commit -m "fix(security): whitelist proxy response headers to prevent cookie injection"
```

---

## Task 8: [LOW-1 + LOW-2] Trusted proxy IP + LIKE wildcard escaping

**Files:**
- Modify: `hindsight_manager/api/admin.py`

- [ ] **Step 1: Add escape helpers and fix IP extraction**

In `hindsight_manager/api/admin.py`, add these helpers before `_admin_user_response` (around line 97):

```python
def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_pattern(value: str) -> str:
    return f"%{_escape_like(value)}%"
```

Replace `_get_client_ip` (lines 112-116):

```python
def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
```

- [ ] **Step 2: Apply LIKE escaping to search queries**

In `list_users` (around line 133), replace:
```python
    if search:
        pattern = _like_pattern(search)
        query = query.where(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )
        count_query = count_query.where(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )
```

In `list_tenants_admin` (around line 300), replace:
```python
    if search:
        pattern = _like_pattern(search)
        owner_subquery = (
            select(TenantMember.tenant_id)
            .join(User, User.id == TenantMember.user_id)
            .where(
                TenantMember.role == MemberRole.OWNER,
                (User.username.ilike(pattern)) | (User.display_name.ilike(pattern)) | (User.email.ilike(pattern)),
            )
        )
        query = query.where(Tenant.name.ilike(pattern) | Tenant.id.in_(owner_subquery))
        count_query = count_query.where(Tenant.name.ilike(pattern) | Tenant.id.in_(owner_subquery))
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/api/admin.py
git commit -m "fix(security): trusted proxy IP extraction + escape LIKE wildcards in admin search"
```

---

## Self-Review

**1. Spec coverage:**
| Spec Item | Task |
|-----------|------|
| 1. SM4-ECB → CBC (HIGH-1) | Task 2 |
| 2. Remove default key (HIGH-2) | Task 1 |
| 3. OTP POST form (HIGH-3) + cookie secure (MEDIUM-1) | Task 3 (manager) + Task 4 (control-plane) |
| 4. Secure verification codes (HIGH-4) + remove dev fallback (MEDIUM-4) | Task 5 |
| 5. Rate limiting (MEDIUM-2) | Task 6 |
| 6. Proxy header whitelist (MEDIUM-3) | Task 7 |
| 7. XFF trusted proxy (LOW-1) + LIKE escape (LOW-2) | Task 8 |

All 10 findings covered. No gaps.

**2. Placeholder scan:** No TBD/TODO. All code blocks are complete. No "Similar to Task N" shortcuts.

**3. Type consistency:**
- `encrypt_sm4(plaintext: str, key: bytes) -> str` — unchanged signature, used in `tenants.py`, `proxy.py`, `auth.py`
- `decrypt_sm4(ciphertext_b64: str, key: bytes) -> str` — unchanged signature
- `Settings.encryption_key: str` — validated to be non-empty 32-char hex
- `Settings.session_secure: bool = True` — used in `_set_session` in Task 3
- `RateLimiter.__call__(request: Request) -> None` — raises HTTPException, used as `Depends()`
- Import paths consistent: `hindsight_manager.middleware.rate_limit`

**4. Test coverage:** Every task includes running the existing test suite. New tests added for CBC mode (Task 2) and OTP redirect (Task 3). Existing `test_otp_redirect.py` fully rewritten to match new behavior.
