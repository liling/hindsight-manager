# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hindsight Manager is a multi-tenant management service for the Hindsight RAG platform. It handles user authentication, tenant provisioning, API key management, and proxies requests to the Hindsight data plane API. It runs alongside the Hindsight API and a Control Plane UI in a Docker Compose setup.

## Commands

```bash
# Install dependencies
uv sync

# Run the dev server
uvicorn hindsight_manager.main:app --reload --port 8001

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_auth_html.py

# Run a specific test
uv run pytest tests/test_crypto.py::test_encrypt_decrypt_roundtrip -v

# Run database migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"

# CLI (admin, auth, tenant subcommands)
hindsight-manager admin --help
hindsight-manager tenant list
```

## Architecture

### Multi-Service Setup

Four services orchestrated via `docker-compose.yml`:
- **postgres** — shared PostgreSQL 16 database
- **hindsight-api** (data plane, port 8888) — the RAG engine; uses `ManagerTenantExtension` to validate API keys
- **manager** (this service, port 8001) — tenant/user management, auth, API proxy
- **control-plane** (port 9999) — admin UI for tenants, authenticates via OTP exchange with manager

### Database Layout

All services share one PostgreSQL instance. The manager uses a `manager` schema (configurable via `HINDSIGHT_MANAGER_MANAGER_SCHEMA`). Each tenant gets its own schema, provisioned lazily on first API key use via Alembic migrations.

Alembic config is in `alembic.ini` with `version_table_schema = manager` so migration history lives in the manager schema.

### Authentication Flow

Two providers: **local** (username/password with bcrypt) and **CAS** (external SSO).

Session flow: login → JWT token set as `hindsight_session` cookie (httponly, 24h TTL). The `get_current_user` dependency in `auth/dependencies.py` reads the cookie or `Authorization: Bearer` header.

**OTP flow** for control plane SSO: authenticated user requests OTP → one-time password (60s TTL, in-memory store) → redirects to control plane with OTP → control plane exchanges OTP for JWT + decrypted system API key.

### API Key Encryption

API keys are encrypted at rest using **SM4** (Chinese national standard, `crypto.py`). The encryption key is configured via `HINDSIGHT_MANAGER_ENCRYPTION_KEY` (hex string, 16 bytes).

### Request Proxy

`api/proxy.py` proxies requests to the data plane. It validates a short-lived access token (15min TTL), resolves the tenant's system API key (decrypted via SM4), and forwards the request to `HINDSIGHT_MANAGER_DATAPLANE_URL`.

### ManagerTenantExtension

`extensions/manager_tenant.py` runs *inside the Hindsight API process* (not the manager). It authenticates incoming API requests by looking up the key hash in `manager.api_keys` and lazily provisions tenant schemas. Batch-updates `last_used_at` every 30 seconds.

### Key Source Layout

```
hindsight_manager/
├── api/            FastAPI routers (auth, tenants, members, api_keys, proxy, pages, password, captcha)
├── auth/           Auth logic (local, CAS, session/JWT, captcha, password hashing)
├── cli/            Typer CLI (admin, auth, tenant subcommands)
├── extensions/     ManagerTenantExtension (loaded by hindsight-api process)
├── models/         SQLAlchemy models (User, Tenant, TenantMember, ApiKey, etc.)
├── services/       Email service (SMTP/SendGrid)
├── migrations/     Alembic migrations
├── templates/      Jinja2 HTML templates
├── static/         CSS/JS assets
├── config.py       Pydantic Settings (env prefix: HINDSIGHT_MANAGER_)
├── crypto.py       SM4 encrypt/decrypt
└── db.py           Async SQLAlchemy engine/session factory
```

### Configuration

All config via environment variables with prefix `HINDSIGHT_MANAGER_` (see `config.py`). Key variables:

- `HINDSIGHT_MANAGER_DATABASE_URL` — asyncpg connection string
- `HINDSIGHT_MANAGER_JWT_SECRET` — JWT signing key
- `HINDSIGHT_MANAGER_ENCRYPTION_KEY` — SM4 key (hex, 16 bytes)
- `HINDSIGHT_MANAGER_ADMIN_PASSWORD` — auto-creates admin user on startup
- `HINDSIGHT_MANAGER_AUTH_PROVIDER` — `local` or `cas`
- `HINDSIGHT_MANAGER_DATAPLANE_URL` — data plane API URL for proxying

## Testing

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. `conftest.py` sets required env vars before app import. Tests mock the database layer — no live Postgres needed.
