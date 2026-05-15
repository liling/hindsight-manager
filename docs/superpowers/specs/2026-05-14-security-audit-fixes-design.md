# Security Audit Fixes Design

**Goal:** Fix all 10 findings from the standard security audit (4 High, 4 Medium, 2 Low).

**Scope:** Two repositories — `hindsight-manager` (primary) and `hindsight-control-plane` (OTP flow).

**Date:** 2026-05-14

---

## 1. SM4-ECB → SM4-CBC (HIGH-1)

**File:** `hindsight_manager/crypto.py`

Replace SM4-ECB with SM4-CBC using random IV. The gmssl library only provides ECB block cipher, so CBC is implemented manually (XOR each block with previous ciphertext block, first block XORed with random IV).

- `encrypt_sm4(plaintext, key)` → generate `os.urandom(16)` IV, CBC-encrypt, output `base64(IV + ciphertext)`
- `decrypt_sm4(ciphertext_b64, key)` → extract IV from first 16 bytes, CBC-decrypt the rest

No backwards compatibility for ECB. System is pre-launch, no existing data.

## 2. Remove Default Encryption Key (HIGH-2)

**File:** `hindsight_manager/config.py`

- Remove default value from `encryption_key` field
- Add `model_validator` that raises `ValueError` if empty or not 16 bytes hex
- Startup fails fast with a clear message including key generation command

## 3. OTP POST Form Redirect (HIGH-3)

**Files:** `hindsight_manager/api/auth.py` (manager), `src/middleware.ts` + new `src/app/api/auth/sso/route.ts` (control-plane)

### Current flow
1. Manager `/auth/otp` returns `{otp, redirect_url: "https://tenant.cp.xxx/?otp=xxx"}`
2. Browser 302 to control-plane URL — OTP visible in URL/logs/referer
3. Control-plane middleware reads `searchParams.get("otp")`
4. Control-plane calls `POST /auth/exchange-otp`, sets cookies

### New flow
1. Manager `/auth/otp` returns `{otp, redirect_url: "https://tenant.cp.xxx/"}` — no OTP in URL
2. Manager new endpoint `GET /auth/otp/redirect?otp=...&tenant_id=...` returns HTML page with auto-submitting POST form
3. Form POSTs `otp` to `https://tenant.cp.xxx/api/auth/sso`
4. Control-plane `/api/auth/sso` (new): receives OTP via POST body, calls manager `/auth/exchange-otp`, sets cookies, redirects to `/dashboard`

### Manager changes
- `OtpResponse.redirect_url` no longer contains OTP
- New `GET /auth/otp/redirect` endpoint renders an inline HTML template:
  ```html
  <form id="f" method="POST" action="{control_plane_url}/api/auth/sso">
    <input type="hidden" name="otp" value="{otp}">
  </form>
  <script>document.getElementById('f').submit()</script>
  ```
- Frontend JS that calls `/auth/otp` should redirect to `/auth/otp/redirect?otp=...&tenant_id=...` after receiving the OTP

### Control-plane changes
- `src/middleware.ts`: remove lines 29-66 (OTP from searchParams logic)
- New `src/app/api/auth/sso/route.ts`: POST handler
  - Receives form data with `otp` field
  - Calls `POST {manager_url}/auth/exchange-otp` with `{"otp": ...}`
  - On success: set `session-jwt` and `tenant-api-key` cookies (same settings as current middleware)
  - Redirect 302 to `/dashboard`
  - On failure: redirect to `/dashboard` (which triggers re-auth via manager)

## 4. Cryptographic Verification Codes (HIGH-4)

**File:** `hindsight_manager/api/password.py`

- `_create_verification_code`: replace `random.choices(string.digits, k=6)` with `"".join(secrets.choice(string.digits) for _ in range(6))`
- No other changes needed

## 5. Session Cookie Secure Flag (MEDIUM-1)

**Files:** `hindsight_manager/config.py`, `hindsight_manager/api/auth.py`

- Add `session_secure: bool = True` to `Settings`
- `_set_session()` reads `settings.session_secure` instead of hardcoded `False`
- Default `True` for production; dev/local can set `HINDSIGHT_MANAGER_SESSION_SECURE=false`

## 6. Rate Limiting (MEDIUM-2)

**Files:** New `hindsight_manager/middleware/__init__.py` + `hindsight_manager/middleware/rate_limit.py`, modify `hindsight_manager/api/auth.py` + `hindsight_manager/api/password.py`

Custom in-memory sliding window rate limiter. No external dependencies.

- Data structure: `dict[str, list[float]]` mapping `"{ip}:{endpoint}"` → list of request timestamps
- Cleanup: evict entries older than window on each check
- Implemented as FastAPI dependency `RateLimiter(max_requests, window_seconds)`
- Applied to:
  - `/auth/login` — 5/minute
  - `/auth/login/form` — 5/minute
  - `/auth/exchange-otp` — 10/minute
  - `/password/forgot` — 3/minute
  - `/password/verify/send` — 3/minute
- Returns HTTP 429 with `Retry-After` header when exceeded

## 7. Proxy Response Header Whitelist (MEDIUM-3)

**File:** `hindsight_manager/api/proxy.py`

Replace the current blacklist approach with a whitelist:

```
Safe headers: content-type, content-disposition, cache-control, etag, x-request-id
```

All other upstream headers (including `set-cookie`, `server`, `x-powered-by`) are dropped.

## 8. Remove Verification Code from Dev Fallback (MEDIUM-4)

**File:** `hindsight_manager/api/password.py`

- `forgot_password` and `send_verification_code` fallback when email service is unavailable:
  - Log the code via `logger.warning` (already done)
  - Return `MessageResponse(message="...")` without the `code` field
  - Remove the `JSONResponse` with `"code": code`

## 9. Trusted Proxy IP Extraction (LOW-1)

**File:** `hindsight_manager/admin.py`

- `_get_client_ip`: take last entry of `X-Forwarded-For` (set by trusted reverse proxy) instead of first (client-controlled)

## 10. LIKE Wildcard Escaping (LOW-2)

**File:** `hindsight_manager/admin.py`

- Add `_escape_like(value)` that escapes `%`, `_`, `\`
- Apply to all `ilike()` patterns in `list_users` and `list_tenants_admin`

---

## Files Changed

### hindsight-manager
| File | Action | Purpose |
|------|--------|---------|
| `crypto.py` | Rewrite | ECB → CBC |
| `config.py` | Modify | Remove default key + validator + session_secure |
| `api/auth.py` | Modify | OTP POST form + secure cookie + rate limit |
| `api/proxy.py` | Modify | Response header whitelist |
| `api/password.py` | Modify | secrets for codes + remove code from response + rate limit |
| `admin.py` | Modify | XFF fix + LIKE escape |
| `middleware/__init__.py` | Create | Empty |
| `middleware/rate_limit.py` | Create | In-memory sliding window limiter |

### hindsight-control-plane
| File | Action | Purpose |
|------|--------|---------|
| `src/middleware.ts` | Modify | Remove OTP from searchParams |
| `src/app/api/auth/sso/route.ts` | Create | POST handler for OTP exchange |
