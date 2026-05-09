# Hindsight Manager UI + Control Plane Integration Design

## Problem

Users need a web UI for hindsight-manager that supports LOCAL and CAS login, tenant management, API key management, and the ability to open the existing Control Plane to view tenant data. When a user has multiple tenants, the Control Plane must show data for the correct tenant. API keys must never appear in the browser.

## Architecture

```
Browser
  |                        |
  | session cookie         | token (header)
  v                        v
Manager UI (Next.js)   Control Plane (Next.js)
  port 3001                port 9999
  |                        |
  +------> Manager API <---+
            port 8001
            /auth/access-token  (issue short-lived JWT)
            /api/proxy/{tenant_id}/**  (reverse proxy)
            /auth/*, /tenants/*  (existing)
                |
                | Authorization: Bearer <system API key>
                v
          hindsight-api (port 8888)
            ManagerTenantExtension validates key -> resolves schema
```

Three services, three responsibilities:
- **Manager UI**: user login, tenant management, issue jump tokens
- **Manager API**: authentication, authorization, API gateway proxy
- **Control Plane**: display bank data, all requests proxied through Manager API

## Manager Backend Changes

### 1. Short-lived Access Token

New endpoint: `POST /auth/access-token`

Request body: `{"tenant_id": "..."}` (user session via cookie)
Response: `{"token": "..."}`

Flow:
1. Decode user session from `hindsight_session` cookie
2. Verify user is a member of the requested tenant (`tenant_members` table)
3. Verify the tenant has a system API key
4. Issue JWT with payload `{sub: user_id, tenant_id: xxx, exp: 15min}` using the same JWT secret as session tokens
5. Return the token

### 2. Generic Reverse Proxy

New route: `/api/proxy/{tenant_id}/{path:path}` (all HTTP methods)

Flow:
1. Read short-lived JWT from `Authorization: Bearer` header
2. Validate JWT, extract `tenant_id`
3. Verify URL `tenant_id` matches token `tenant_id`
4. Query DB for the tenant's system API key (decrypt `encrypted_key`)
5. Forward the request to `hindsight-api/v1/default/{path}` with `Authorization: Bearer <system_key>`
6. Return hindsight-api response as-is (status, headers, body)

Pure pass-through proxy. No request/response body parsing.

### 3. System API Key

Each tenant gets an auto-generated system API key on creation. Stored as:
- `key_hash`: SHA-256 hash (for TenantExtension validation in hindsight-api)
- `key_prefix`: first 16 chars (for display)
- `encrypted_key`: AES-encrypted original key (for Manager proxy to decrypt and use)
- `is_system`: `true`

Non-system keys (user-created) store only `key_hash` and `key_prefix`, same as current behavior. `encrypted_key` is NULL for non-system keys.

Encryption key: Manager's `HINDSIGHT_MANAGER_JWT_SECRET` (reuse existing secret).

### 4. API Key Endpoints Changes

- `DELETE /tenants/{id}/api-keys/{key_id}`: return 403 if `is_system=True`
- `GET /tenants/{id}/api-keys`: include `is_system` field in response
- `POST /tenants`: auto-generate system API key after tenant creation

### 5. Data Model Changes

```sql
ALTER TABLE manager.api_keys
  ADD COLUMN is_system boolean NOT NULL DEFAULT false,
  ADD COLUMN encrypted_key text;
```

## Control Plane Changes

### 1. Configuration

```bash
HINDSIGHT_CP_DATAPLANE_API_URL=http://localhost:8001/api/proxy
# HINDSIGHT_CP_DATAPLANE_API_KEY no longer required when using Manager proxy
```

Fallback: if `HINDSIGHT_CP_DATAPLANE_API_KEY` is set, use it directly (standalone mode without Manager).

### 2. Backend (`src/lib/hindsight-client.ts`)

- `getDataplaneKey()`: extract token from request header `x-hindsight-token`, fall back to env var
- `dataplaneBankUrl()`: prepend `tenant_id` from `x-hindsight-tenant` header
- All three clients (`hindsightClient`, `lowLevelClient`, `getDataplaneHeaders`) accept dynamic token

### 3. API Routes (`src/app/api/**/*.ts`)

Each route extracts `x-hindsight-token` and `x-hindsight-tenant` from incoming request, passes to client functions. Helper function in `src/lib/get-token.ts`:

```typescript
export function getToken(request: NextRequest): string {
  return request.headers.get("x-hindsight-token")
    || process.env.HINDSIGHT_CP_DATAPLANE_API_KEY
    || "";
}
```

### 4. Frontend

Entry point reads URL query params: `?token=xxx&tenant_id=yyy`
- Store token in `sessionStorage` (cleared when tab closes)
- Include `x-hindsight-token` and `x-hindsight-tenant` headers in all `/api/*` calls
- On 401: show "session expired, return to Manager UI" message with link

## Manager UI (hindsight-manager-ui)

New independent Next.js 15 project (App Router).

### Pages

```
/login              -> Login page (LOCAL / CAS tabs)
/tenants            -> Tenant list (home page)
/tenants/:id        -> Tenant detail (members + API keys tabs)
```

### Login Page

- LOCAL tab: username + password form -> `POST /auth/login`
- CAS tab: "Login with CAS" button -> redirect to Manager `GET /auth/cas/login`, callback auto-login
- On success: redirect to `/tenants`

### Tenant List Page

- Show all tenants the user belongs to
- Each card: name, status, member count, created time
- "Create tenant" button -> modal with name input
- "Open Control Panel" button -> `POST /auth/access-token` -> new tab `control-plane-url?token=xxx&tenant_id=yyy`
- Owner can soft-delete tenant

### Tenant Detail Page

Two tabs:

**Members tab**: member list (username, role, joined time). Owner can add/remove members, change roles.

**API Keys tab**: key list (name, prefix, created time, is_system flag). System key marked as "System Key" with no delete button. "Create API Key" button shows full key once. Owner can delete non-system keys.

### Tech Stack

- Next.js 15 (App Router)
- shadcn/ui (consistent with Control Plane)
- React Query (API data fetching/caching)
- Tailwind CSS

### API Communication

Manager UI calls Manager API endpoints. If same-origin (both on localhost or same domain), browser sends `hindsight_session` cookie automatically. If cross-origin, configure Manager UI Next.js API routes as proxy to Manager API.

## Security

### Short-lived Token

- 15 minute expiry, no renewal
- Bound to `tenant_id` and `user_id`
- Manager proxy validates token tenant_id matches URL tenant_id
- Same JWT secret as session tokens

### System API Key

- Original key AES-encrypted in `encrypted_key` column
- Raw key never returned in any API response or shown in any UI
- Only the Manager proxy decrypts and injects it into requests to hindsight-api

### Error Handling

| Scenario | Response |
|----------|----------|
| Short-lived token expired | 401, Control Plane shows "return to Manager UI" |
| User not tenant member | 403 |
| Tenant not ACTIVE | 403 |
| System key missing | 500 |
| hindsight-api unavailable | 502, passthrough error |
| Control Plane token expired | Frontend prompt with return link |
