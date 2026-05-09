# Manager API Proxy MVP Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** In `hindsight-manager` 中新增反向代理路由和短期访问令牌，打通 SaaS 宿主 → Manager API → hindsight-api 的端到端链路。

**Architecture:** Manager API 作为 API 网关，验证短期 JWT 后解密租户的系统级 API Key，注入 Authorization header 转发到 hindsight-api。SaaS 宿主只接触短期令牌，永远不接触真实 API Key。

**Tech Stack:** FastAPI, SQLAlchemy (async), python-jose (JWT), gmssl (SM4 encryption), httpx (proxy)

---

## 1. Background

`hindsight-manager` (port 8001, FastAPI) 已有完整基础：
- 用户认证（LOCAL/CAS）, JWT session cookie (24h)
- 租户 CRUD (`/tenants`)
- 成员管理 (`/tenants/{id}/members`)
- API Key 管理 (`/tenants/{id}/api-keys`) — 当前只存 key_hash (SHA256)
- `TenantExtension` 插件给 hindsight-api 用

**缺失：** 无反向代理路由，无短期访问令牌。

SaaS 宿主 (hindsight-saas-host) 已实现前端集成（Control Plane 作为 npm 包嵌入），API 代理路由 `hindsight-saas-host/src/app/api/proxy/[tenantId]/[...path]/route.ts` 已存在但只做简单转发到 Manager API。

## 2. Data Model Changes

### 2.1 `api_keys` 表新增列

在 `hindsight_manager/models/api_key.py` 的 `ApiKey` 模型中新增：

```python
is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- `is_system` — 标记系统级 key（代理专用），不可删除、不对用户展示
- `encrypted_key` — SM4-ECB 加密后的原始 API Key（base64 编码）

### 2.2 租户创建时自动生成系统级 API Key

修改 `hindsight_manager/api/tenants.py` 的 `create_tenant()` 端点：

1. 创建租户后
2. 生成系统级 API Key（格式 `hsm_` + 32 hex chars）
3. 计算 `key_hash`（SHA256）
4. 用 SM4-ECB 加密原始 key，base64 编码后存入 `encrypted_key`
5. 设置 `is_system=True`
6. 存入 `api_keys` 表

原始 key 不返回给调用方。

### 2.3 Alembic 迁移

新增迁移文件，在 `manager` schema 的 `api_keys` 表上添加两列：

```sql
ALTER TABLE manager.api_keys ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE manager.api_keys ADD COLUMN encrypted_key TEXT;
```

## 3. SM4 Encryption

### 3.1 加密工具

新增 `hindsight_manager/crypto.py`：

```python
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT
import base64

def encrypt_sm4(plaintext: str, key: bytes) -> str:
    """SM4-ECB encrypt, returns base64 encoded ciphertext."""
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_ENCRYPT)
    # PKCS7 padding to 16-byte blocks
    data = plaintext.encode()
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len] * pad_len)
    ciphertext = sm4.crypt_ecb(data)
    return base64.b64encode(ciphertext).decode()

def decrypt_sm4(ciphertext_b64: str, key: bytes) -> str:
    """SM4-ECB decrypt from base64 encoded ciphertext."""
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT)
    ciphertext = base64.b64decode(ciphertext_b64)
    plaintext_padded = sm4.crypt_ecb(ciphertext)
    # Remove PKCS7 padding
    pad_len = plaintext_padded[-1]
    return plaintext_padded[:-pad_len].decode()
```

### 3.2 密钥配置

新增环境变量 `HINDSIGHT_MANAGER_ENCRYPTION_KEY`（32 hex chars = 128-bit SM4 key）。

在 `Settings` 中：
```python
encryption_key: str  # 32 hex chars
```

运行时转换为 bytes:
```python
key_bytes = bytes.fromhex(settings.encryption_key)
```

## 4. Short-Lived Access Token

### 4.1 新增端点: `POST /auth/access-token`

```
POST /auth/access-token?tenant_id=<uuid>
Cookie: hindsight_session=<session_jwt>
```

**处理逻辑：**

1. 从 `hindsight_session` cookie 获取当前用户（复用 `get_current_user` 依赖）
2. 验证用户是 `tenant_id` 的成员（查 `tenant_members` 表）
3. 签发短期 JWT：
   ```json
   {
     "sub": "<user_id>",
     "tid": "<tenant_id>",
     "exp": "<now + 15min>",
     "type": "access"
   }
   ```
4. 返回：
   ```json
   {
     "access_token": "eyJ...",
     "expires_in": 900,
     "tenant_id": "<uuid>"
   }
   ```

### 4.2 Session 模块变更

在 `hindsight_manager/auth/session.py` 中新增：

```python
ACCESS_TOKEN_EXPIRE_MINUTES = 15

def create_access_token(
    user_id: str,
    tenant_id: str,
    secret: str,
) -> str:
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

## 5. Reverse Proxy Route

### 5.1 新增文件: `hindsight_manager/api/proxy.py`

通用反向代理路由，处理所有 HTTP 方法：

```
ANY /api/proxy/{tenant_id}/{path:path}
Authorization: Bearer <access_token>
```

**处理逻辑：**

1. 从 `Authorization: Bearer <token>` 提取 access token
2. 调用 `verify_access_token(token, secret, tenant_id)` 验证
3. 从 `api_keys` 表查询 `tenant_id` 且 `is_system=True` 的记录
4. 调用 `decrypt_sm4(encrypted_key, key_bytes)` 解密系统 API Key
5. 用 `httpx.AsyncClient` 转发请求到 `HINDSIGHT_MANAGER_DATAPLANE_URL/<path>`:
   - 替换 `Authorization` header 为解密后的系统 API Key
   - 透传 Content-Type、request body、query params
6. 返回 upstream 的 response（status code、headers、body）

### 5.2 配置

新增环境变量 `HINDSIGHT_MANAGER_DATAPLANE_URL`（默认 `http://localhost:8888`）。

在 `Settings` 中：
```python
dataplane_url: str = "http://localhost:8888"
```

### 5.3 注册路由

在 `hindsight_manager/main.py` 中：
```python
from hindsight_manager.api.proxy import router as proxy_router
app.include_router(proxy_router)
```

## 6. HTTP Methods

代理路由支持以下方法：

| Method | 透传 Body | 用途 |
|--------|-----------|------|
| GET | No | 查询（recall、list banks 等） |
| POST | Yes | 创建（retain、create bank 等） |
| PUT | Yes | 全量更新 |
| PATCH | Yes | 部分更新 |
| DELETE | No | 删除 |

所有方法透传 query parameters 和 Content-Type。

## 7. Error Handling

| 场景 | HTTP Status | 响应 |
|------|-------------|------|
| 缺少 Authorization header | 401 | `{ "detail": "Missing authorization token" }` |
| JWT 无效/过期 | 401 | `{ "detail": "Invalid or expired token" }` |
| JWT 中 tid 与 URL tenant_id 不匹配 | 403 | `{ "detail": "Tenant ID mismatch" }` |
| 找不到系统级 API Key | 500 | `{ "detail": "No system API key found for tenant" }` |
| Upstream 超时 (30s) | 504 | `{ "detail": "Upstream timeout" }` |
| Upstream 返回错误 | 透传 | 透传 upstream 的 status code 和 body |

## 8. API Key 列表过滤

修改 `hindsight_manager/api/api_keys.py` 的 `list_api_keys()` 端点：
- 只返回 `is_system=False` 的 key（用户创建的 key）
- 系统级 key 不对用户展示

## 9. Files Changed

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `hindsight_manager/models/api_key.py` | 修改 | 新增 `is_system`、`encrypted_key` 列 |
| `hindsight_manager/crypto.py` | 新建 | SM4 加解密工具函数 |
| `hindsight_manager/auth/session.py` | 修改 | 新增 `create_access_token()`、`verify_access_token()` |
| `hindsight_manager/api/auth.py` | 修改 | 新增 `POST /auth/access-token` 端点 |
| `hindsight_manager/api/proxy.py` | 新建 | 通用反向代理路由 |
| `hindsight_manager/api/tenants.py` | 修改 | 创建租户时自动生成系统级 API Key |
| `hindsight_manager/api/api_keys.py` | 修改 | 列表过滤掉系统级 key |
| `hindsight_manager/config.py` | 修改 | 新增 `encryption_key`、`dataplane_url` 配置 |
| `hindsight_manager/main.py` | 修改 | 注册 proxy router |
| `hindsight_manager/migrations/versions/002_add_system_api_key.py` | 新建 | 数据库迁移 |

## 10. Sequence Diagram

```
User clicks "打开记忆管理" on SaaS Host Dashboard
  │
  ▼
SaaS Host → POST http://manager:8001/auth/access-token?tenant_id=xxx
            Cookie: hindsight_session=<24h_jwt>
  │
  ▼
Manager API: verify session → verify membership → issue 15min JWT
  │
  ▼
SaaS Host ← { access_token: "eyJ...", expires_in: 900 }
  │
  ▼
Browser opens: /tenant_xxx?token=eyJ...
  │
  ▼
Control Plane loads, reads token from URL, stores in sessionStorage
  │
  ▼
CP makes API call → SaaS Host /api/proxy/tenant_xxx/banks
                    Authorization: Bearer eyJ...
  │
  ▼
SaaS Host forwards → Manager:8001 /api/proxy/tenant_xxx/banks
                     Authorization: Bearer eyJ...
  │
  ▼
Manager: verify JWT → decrypt SM4(system_key) → forward to hindsight-api:8888
         Authorization: hsm_xxxxx
  │
  ▼
hindsight-api processes request → returns data
  │
  ▼
Response flows back: hindsight-api → Manager → SaaS Host → CP
```

## 11. Out of Scope (Future Iterations)

- 用户注册端点
- Admin 管理面板
- API Key 轮换（重新生成系统级 key）
- Token 刷新（前端自动续签 access token）
- Rate limiting
- 审计日志
