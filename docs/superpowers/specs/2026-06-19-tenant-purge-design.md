# 租户清空（Purge）功能设计

## 背景与范围

### 现状

当前"删除租户"是软删除：`DELETE /admin/api/tenants/{id}` 和 `DELETE /tenants/{id}` 只把 `tenant.status` 从 `ACTIVE` 改为 `DELETING`，没有任何后续清理。

后果：
- `manager.tenants` 行永远停留在 DELETING
- 租户的业务数据（独立 PostgreSQL schema，如 `tenant_xxxxxxxx`）永远保留在磁盘上
- 管理员无法在 UI 上区分"待清空"和"已清空"的租户
- 没有任何路径可以真正回收空间

### 本次范围

新增一个**管理员专属的"清空"操作**：对 DELETING 状态的租户，DROP 其业务 schema，并把状态推进到 DELETED。

```
ACTIVE  ──[owner/admin DELETE]──▶  DELETING  ──[admin purge]──▶  DELETED
```

### 明确不做（YAGNI）

- 不删 `manager.tenants` / `tenant_members` / `api_keys` 元数据行（保留追溯能力）
- 不做后台定时自动清空（手动触发即可）
- 不做 dry-run 模式
- 不做 `--force` 跳过状态检查
- 不做"显示已删除租户"的 UI 开关
- 不动 `ManagerTenantExtension`（它已用 `status = 'ACTIVE'` 过滤，DELETED 自动失效）

## 架构总览

新增管理员接口 + CLI + UI 按钮，与现有软删除解耦：

```
用户点"删除"  →  ACTIVE → DELETING       (现状，不动)
管理员点"清空" →  DELETING → DELETED     (新增)
                + DROP SCHEMA tenant_xxx CASCADE
```

**新增组件：**

| 位置 | 改动 |
|------|------|
| `models/tenant.py` | `TenantStatus` 新增 `DELETED = "deleted"` |
| `migrations/versions/` | 新 Alembic revision，给 `tenant_status` enum 加 `'deleted'` 值 |
| `api/admin.py` | 新接口 `POST /admin/api/tenants/{id}/purge`（管理员鉴权） |
| `cli/tenant.py` | 新命令 `hindsight-manager tenant purge <id>` |
| `static/admin.js` + `templates/admin_tenants.html` | 行内"清空"按钮（仅 DELETING 行显示） |
| 审计 | 写 `tenant.purge` 动作 |

**不动：**
- `ManagerTenantExtension` —— 已用 `t.status = 'ACTIVE'` 过滤
- 现有软删除端点（`DELETE /admin/api/tenants/{id}`、`DELETE /tenants/{id}`）行为不变
- 现有"删除"按钮不变

### 为什么用 POST /purge 子资源

`purge` 是动作不是 CRUD。POST 子资源与现有 DELETE（软删）语义分开，避免一个端点两种行为。对比 `DELETE /tenants/{id}?hard=true` —— 模糊、易误用。

## 接口契约

### `POST /admin/api/tenants/{id}/purge`

- **鉴权**：管理员（`require_admin` 依赖）
- **请求体**：无
- **成功响应**：200 `{"ok": true, "schema_dropped": <bool>}`
- **错误响应**：
  - 404：租户不存在
  - 403：非管理员
  - 409：状态非 DELETING（active 或 deleted），提示需先软删除
  - 500：schema_name 异常或 DROP SCHEMA 失败

### 执行步骤

```
1. 鉴权：require_admin
2. 查租户 + 行锁：SELECT ... FOR UPDATE
   └─ 不存在 → 404
   └─ 锁序列化并发 purge，第二个请求会阻塞到第一个提交
3. 状态检查（持锁状态下）：status != DELETING → 409
4. 校验 schema_name：必须匹配 ^tenant_[a-f0-9]{8}$，否则 500
   └─ 防止 SQL 注入：schema 名无法参数化，必须字符串拼接 + 白名单
5. 在同一事务里：
   a. DROP SCHEMA IF EXISTS <schema> CASCADE
      └─ 捕获返回值判断是否真的 drop 了（rowcount 或前后查询对比）
   b. UPDATE tenants SET status = 'DELETED' WHERE id = :id
   c. INSERT audit_logs (action='tenant.purge', detail={name, schema_name, schema_dropped})
6. 提交事务，返回 {ok: true, schema_dropped: <bool>}
```

### 关键决策

- **幂等**：`DROP SCHEMA IF EXISTS` 不因 schema 不存在而失败（租户从未被访问、schema 没懒创建时也能正常清空）。可安全重试。
- **事务性**：PG 支持事务化 DDL。若 DROP SCHEMA 失败，状态保持 DELETING，可重试。
- **并发保护**：步骤 2 用 `SELECT FOR UPDATE` 序列化同一租户的并发 purge。第二个请求阻塞到第一个提交后，再读到 `status = 'DELETED'`，步骤 3 返回 409。这样并发语义清晰：成功者返回 200，失败者返回 409。
- **schema_name 校验**：所有创建路径都生成 `tenant_{uuid.hex[:8]}`，正则 `^tenant_[a-f0-9]{8}$` 是严格白名单。不符则 500，不执行 DROP。
- **schema 不存在仍标记 DELETED**：避免卡死；返回 `schema_dropped: false` 供调用方感知。
- **不删 manager.tenants 行**（按"仅业务数据"决策）。

## UI 设计

### `admin_tenants.html` + `admin.js`

行内操作按钮按状态切换：

| 状态 | "删除"按钮 | "清空"按钮 | 行样式 |
|------|-----------|-----------|--------|
| active | 显示 | 隐藏 | 正常 |
| deleting | 隐藏 | 显示 | 正常（badge 标"待清空"） |
| deleted | 隐藏 | 隐藏 | 不出现在列表中 |

列表查询过滤 `WHERE status IN ('active', 'deleting')`。已清空的租户可从审计日志查。

### "清空"按钮确认弹窗

不可逆操作，要求用户手打租户名确认：

```
确定要彻底清空租户 "<name>" 的所有业务数据吗？
此操作不可撤销，将删除 schema <schema_name> 下的所有数据。

[输入租户名确认]

[取消] [确认清空]
```

确认按钮在输入与租户名完全匹配前禁用。

### Badge 显示

`deleting` 状态在状态列显示黄色 badge，文案"待清空"，区别于 active 的绿色 badge。

## CLI

新增命令：

```bash
hindsight-manager tenant purge <tenant_id>
```

- 调 `POST /admin/api/tenants/{id}/purge`
- 成功输出：`Purged tenant <name>: schema_dropped=<true/false>`
- 409 时提示：`Tenant is not in DELETING state. Run 'hindsight-manager tenant delete <id>' first.`

## 数据库迁移

新 Alembic revision：

```python
def upgrade():
    op.execute("ALTER TYPE tenant_status ADD VALUE IF NOT EXISTS 'deleted'")

def downgrade():
    # PostgreSQL 不支持直接从 enum 移除值
    # downgrade 需要重建类型，留空或抛 NotImplementedError
    pass
```

`version_table_schema = manager`，迁移历史在 manager schema。

注意：`ADD VALUE` 不能在事务块里执行（PG 限制），Alembic 需 `transactional_ddl=False` 或显式 `autocommit` block。

## 测试策略

### 新增测试文件 `tests/test_tenant_purge.py`

全部用现有 mock DB 模式，不打真 Postgres：

| 测试 | 验证 |
|------|------|
| `test_purge_requires_admin` | 非管理员 → 403 |
| `test_purge_unknown_tenant_404` | 租户不存在 → 404 |
| `test_purge_active_tenant_409` | status=ACTIVE → 409，schema 不动 |
| `test_purge_deleted_tenant_409` | status=DELETED → 409（幂等保护） |
| `test_purge_deleting_tenant_success` | 正常路径：DROP SCHEMA 调用一次，status 更新为 DELETED，audit 写入 |
| `test_purge_when_schema_missing` | DROP SCHEMA IF EXISTS 不报错，status 仍更新为 DELETED，返回 `schema_dropped: false` |
| `test_purge_invalid_schema_name_500` | schema_name 不符正则（构造异常数据）→ 500，不执行 DROP |
| `test_purge_concurrent_double_click` | 模拟 SELECT FOR UPDATE 序列化：第二次调用读到 status=DELETED → 409 |
| `test_audit_log_entry` | audit_logs 写入 `tenant.purge`，detail 含 name/schema_name/schema_dropped |

### 不破坏现有测试

- 现有 `test_auth_html.py`、`test_crypto.py` 等不动
- `uv run pytest` 全套不退化
- `alembic upgrade head` 在干净库上成功

### 手动验证（实现完成后）

1. 起服务，创建租户 → 软删 → 查列表显示 DELETING
2. 调 purge 接口 → schema 真的被 DROP（用 psql 查 `\dn`）
3. 列表里该租户消失（DELETED 被过滤）
4. 审计日志里有 `tenant.purge` 记录
5. 用该租户的 API key 调 hindsight-api → 认证失败

## 实现顺序（供后续 plan 参考）

1. 加 `TenantStatus.DELETED` + migration
2. 后端 purge 端点 + 审计
3. 单元测试
4. CLI 命令
5. UI 按钮 + 确认弹窗 + badge
6. 手动验证 + 文档（如有需要）
