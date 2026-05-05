# Hindsight Manager Design Spec

## Overview

Hindsight Manager is a standalone tenant management service for Hindsight. It handles user authentication (CAS or local username/password), tenant provisioning, member management, API key lifecycle, and per-tenant model configuration.

It is a separate project at `../hindsight-manager`, built with Python/FastAPI. Data-plane operations remain in hindsight-api; the manager only manages metadata.

## Architecture

```
Users (browser) --CAS/LOCAL--> hindsight-manager (:8001)  [management plane]
                                 |
                                 | read/write metadata
                                 v
                            PostgreSQL
                           /             \
               manager schema          tenant_{id} schemas
               (users, tenants,         (memory data,
                members, api_keys)       managed by hindsight-api)
                                 ^
                                 | read metadata (schema_name, config)
                                 v
Apps (SDK) --API Key--> hindsight-api (:8000)  [data plane]
                      + ManagerTenantExtension
```

**Key principle**: manager creates metadata; hindsight-api reads it and provisions schemas on first access. The two services share the same PostgreSQL instance but use different schemas.

## Authentication

Two strategies, configurable via `AUTH_PROVIDER` env var (`local|cas`):

### Local Auth
- Username + password stored in `users` table (bcrypt hash)
- `POST /auth/login` with `{"provider": "local", "username": "...", "password": "..."}`

### CAS Auth (Apereo CAS)
- `GET /auth/cas/login` redirects to CAS server
- `GET /auth/cas/callback` validates ticket, creates session

### Session
Both strategies issue a JWT session token (httpOnly cookie). JWT secret configured via `JWT_SECRET`.

## Database Schema

All tables live in the `manager` schema (configurable via `MANAGER_SCHEMA`).

### users

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| username | varchar | Unique. CAS username or local username |
| password_hash | varchar | bcrypt, nullable (NULL for CAS users) |
| display_name | varchar | |
| auth_provider | enum(LOCAL, CAS) | |
| created_at | timestamp | |

### tenants

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| name | varchar | Human-readable name |
| schema_name | varchar | PostgreSQL schema, e.g. `tenant_a1b2c3` |
| config | JSONB | Tenant-level config (model credentials only) |
| status | enum(active, deleting) | |
| created_at | timestamp | |

### tenant_members

| Column | Type | Notes |
|---|---|---|
| user_id | UUID | FK -> users |
| tenant_id | UUID | FK -> tenants |
| role | enum(owner, member) | |
| created_at | timestamp | |

PK: (user_id, tenant_id)

### api_keys

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| tenant_id | UUID | FK -> tenants |
| key_hash | varchar | SHA-256 of the full API key |
| key_prefix | varchar | First 8 chars for display (e.g. `hsm_xxxxxxxx`) |
| name | varchar | User-given label |
| created_at | timestamp | |
| last_used_at | timestamp | Nullable, updated on each auth |

## Tenant Config

Only model/credential fields are managed at the tenant level. Behavioral tuning (chunk_size, disposition, recall budget, etc.) is configured per-bank via hindsight-api's existing bank-config API.

Config resolution hierarchy: `global env vars -> tenant config -> bank config`

### Tenant-level config fields (stored in `tenants.config` JSONB)

| Field | Description |
|---|---|
| llm_provider | LLM provider (openai, anthropic, gemini, groq, ...) |
| llm_model | Model name |
| llm_api_key | API key |
| llm_base_url | Custom endpoint |
| embeddings_provider | Embeddings provider (local, tei) |
| embeddings_model | Model name |
| embeddings_api_key | API key |
| embeddings_base_url | Endpoint |
| reranker_provider | Reranker provider (local, tei) |
| reranker_model | Model name |
| reranker_api_key | API key |

Fields set to null fall back to server-wide global defaults.

## Schema Provisioning

Managed by hindsight-api's `ManagerTenantExtension`, not by the manager itself:

1. Manager creates a tenant record (status=active) in metadata
2. First request with that tenant's API Key hits hindsight-api
3. `ManagerTenantExtension.authenticate()` looks up the API key, gets `schema_name`
4. Checks in-memory `_initialized_schemas` set; if not present, calls `run_migration(schema_name)`
5. Subsequent requests skip provisioning

Manager never calls hindsight-api and never directly creates data schemas.

## ManagerTenantExtension (hindsight-api side)

A custom `TenantExtension` subclass in hindsight-api that:

- **authenticate()**: Extracts API key from `Authorization: Bearer <key>` or `X-API-Key: <key>` header, SHA-256 hashes it, queries `manager.api_keys` joined with `manager.tenants` to get `schema_name` and verify `status = active`
- **get_tenant_config()**: Reads `tenants.config` JSONB, returns as dict with snake_case keys matching `HindsightConfig` fields
- **list_tenants()**: Queries `SELECT schema_name FROM manager.tenants WHERE status = 'active'` for worker polling

## REST API

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /auth/login | No | Login (local or CAS) |
| GET | /auth/cas/login | No | Redirect to CAS |
| GET | /auth/cas/callback | No | CAS callback |
| POST | /auth/logout | Yes | Logout |
| GET | /auth/me | Yes | Current user info |
| GET | /tenants | Yes | User's tenants |
| POST | /tenants | Yes | Create tenant |
| GET | /tenants/{id} | Yes + member | Tenant detail |
| PATCH | /tenants/{id} | Yes + owner | Update tenant config |
| DELETE | /tenants/{id} | Yes + owner | Delete tenant |
| GET | /tenants/{id}/members | Yes + member | List members |
| POST | /tenants/{id}/members | Yes + owner | Add member |
| DELETE | /tenants/{id}/members/{user_id} | Yes + owner | Remove member |
| PATCH | /tenants/{id}/members/{user_id} | Yes + owner | Change role |
| POST | /tenants/{id}/api-keys | Yes + owner | Create API key |
| GET | /tenants/{id}/api-keys | Yes + member | List API keys (prefixed) |
| DELETE | /tenants/{id}/api-keys/{key_id} | Yes + owner | Revoke API key |

## CLI

```bash
hindsight-manager auth login                    # Local login (interactive)
hindsight-manager auth logout
hindsight-manager tenant list
hindsight-manager tenant create --name "my-app"
hindsight-manager tenant show <id>
hindsight-manager tenant config set <id> --llm-provider openai --llm-model gpt-4o
hindsight-manager tenant config get <id>
hindsight-manager tenant delete <id>
hindsight-manager tenant member list <id>
hindsight-manager tenant member add <id> --user <username> --role member
hindsight-manager tenant member remove <id> --user <username>
hindsight-manager tenant member role <id> --user <username> --role owner
hindsight-manager tenant api-key create <id> --name "my-key"
hindsight-manager tenant api-key list <id>
hindsight-manager tenant api-key revoke <id> <key_id>
```

## Tech Stack

- **Framework**: FastAPI + uvicorn
- **ORM**: SQLAlchemy async + asyncpg
- **CLI**: Typer
- **Auth**: passlib[bcrypt], python-jose (JWT), python-cas
- **Migrations**: Alembic (for manager's own metadata tables)
- **Package manager**: uv

## Project Structure

```
../hindsight-manager/
├── pyproject.toml
├── hindsight_manager/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Env var configuration
│   ├── db.py                   # SQLAlchemy async engine + session
│   ├── models/
│   │   ├── user.py
│   │   ├── tenant.py
│   │   ├── tenant_member.py
│   │   └── api_key.py
│   ├── auth/
│   │   ├── cas.py
│   │   ├── local.py
│   │   └── session.py          # JWT session management
│   ├── api/
│   │   ├── auth.py
│   │   ├── tenants.py
│   │   └── members.py
│   └── cli/
│       ├── auth.py
│       ├── tenant.py
│       └── config.py
├── hindsight_manager/migrations/  # Alembic for metadata tables
└── tests/
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| DATABASE_URL | PostgreSQL connection string | (required) |
| MANAGER_SCHEMA | Metadata schema name | `manager` |
| AUTH_PROVIDER | `local`, `cas`, or both (comma-separated) | `local` |
| CAS_SERVER_URL | CAS server URL | (CAS mode) |
| CAS_SERVICE_URL | This service's callback URL | (CAS mode) |
| JWT_SECRET | JWT signing secret | (required) |
| HOST | Listen host | `0.0.0.0` |
| PORT | Listen port | `8001` |
