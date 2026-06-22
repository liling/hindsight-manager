# Hindsight Manager

Business layer for the Hindsight RAG platform: tenant management, API key issuance,
data-plane proxy, and task monitoring. Authentication, user management, and audit
are delegated to the **xinyi-platform** service.

## xinyi-platform Integration

HM delegates authentication, user management, and audit to xinyi-platform.
See `docs/superpowers/specs/2026-06-22-platform-extraction-design.md` for the
full design.

### Required environment

HM's `.env` must include:

- `HINDSIGHT_MANAGER_JWT_SECRET` — **must match** xinyi-platform's `XINYI_PLATFORM_JWT_SECRET`
- `HINDSIGHT_MANAGER_ENCRYPTION_KEY` — **must match** xinyi-platform's `XINYI_PLATFORM_ENCRYPTION_KEY`
- `HINDSIGHT_MANAGER_PLATFORM_URL=http://xinyi-platform:8000`
- `HINDSIGHT_MANAGER_OAUTH_CLIENT_ID=hm-prod`
- `HINDSIGHT_MANAGER_OAUTH_CLIENT_SECRET=<raw secret>`
- `HINDSIGHT_MANAGER_OAUTH_REDIRECT_URI=http://hm:8001/auth/callback`

### Local development

1. Start xinyi-platform (see its README)
2. Register `hm-prod` client in platform's `/admin/clients`
3. Start HM with the above env vars
4. Visit http://localhost:8001/admin/tenants → redirected to platform login → back to HM

### HM auth flow

- `GET /auth/login-redirect?return_to=...` — 302 to `{platform}/oauth/authorize`
- `GET /auth/callback?code=...&state=...` — exchanges code, sets `hindsight_session` + `hindsight_refresh` cookies, 303 to return_to
- `POST /auth/refresh` — refreshes access cookie using `hindsight_refresh`
- `POST /auth/logout` — clears cookies, revokes refresh token at platform

### Data flow

- User info: HM calls `POST /internal/users/batch-get` (X-Client-Id + X-Client-Secret) → caches in process-local LRU (5min TTL)
- User lookup by username: `GET /internal/users/by-username/{username}`
- Audit push: enqueued to local `manager.audit_outbox` table, APScheduler task retries every 10s, posts to `POST /internal/audit`
- Revocation check: `POST /internal/auth/check-revocation` (called when access token is expired)

## Development

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn hindsight_manager.main:app --reload --port 8001
```

## Tests

```bash
uv run pytest                                  # all tests
uv run pytest --ignore=tests/test_manager_tenant.py  # skip env-only test
uv run pytest tests/integration/                 # OAuth2 round-trip
uv run pytest tests/platform_tests/             # xinyi-platform client
```

## Architecture

```
hindsight_manager/
├── auth/
│   ├── dependencies.py        # get_current_user returns dict from local JWT verify
│   ├── session.py             # data-plane access token + OTP + JWT decode helper
│   ├── oauth_state.py         # HMAC-signed OAuth state
│   └── audit.py               # record_audit → enqueue to audit_outbox
├── models/
│   ├── tenant.py, tenant_member.py, api_key.py, audit_outbox.py
├── services/
│   ├── tenant_service.py, member_service.py, membership.py
│   ├── api_key_service.py, audit_outbox_service.py
├── platform/                  # XinyiPlatformClient + UserLRUCache + PlatformSettings
├── api/
│   ├── auth.py                # OAuth2 client endpoints + access-token + OTP
│   ├── admin.py               # tenant/api-key CRUD; user-mgmt and audit redirected to platform
│   ├── tenants.py, members.py, api_keys.py, proxy.py, task_monitor.py, pages.py
└── migrations/                # Alembic
    └── versions/006_add_audit_outbox.py
    └── versions/007_drop_infra_tables.py (Phase 5 only)
```

## Plan B docs

- `docs/superpowers/plans/2026-06-22-xinyi-platform-hm-refactor.md` — implementation plan
- `docs/superpowers/specs/2026-06-22-platform-extraction-design.md` — overall design
- `docs/superpowers/data-migration/` — SQL migration scripts
- `docs/superpowers/data-migration/cutover-runbook.md` — Phase 4 cutover steps