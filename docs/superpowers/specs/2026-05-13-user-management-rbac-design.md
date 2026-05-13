# 用户管理与 RBAC 权限设计

日期：2026-05-13

## 背景

当前系统通过硬编码 `username == "admin"` 判断管理员权限，没有角色系统和用户管理界面。需要添加系统级 RBAC 和完整的后台管理功能。

## 方案

在 User 模型添加 `role` 枚举字段（`admin` / `user`），通过 FastAPI 依赖统一权限校验。不做独立的角色/权限表，两个角色用枚举足够。

## 一、数据模型与角色系统

### UserRole 枚举

```python
class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
```

### User 模型变更

- 新增 `role` 字段，类型 `UserRole`，默认值 `USER`
- 删除所有 `username == "admin"` 的硬编码判断

### 数据库迁移

- 添加 `role` 列（VARCHAR，默认 `'user'`）
- 数据迁移：`UPDATE users SET role = 'admin' WHERE username = 'admin'`

### 权限依赖

`auth/dependencies.py` 新增：

```python
def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(403, "需要管理员权限")
    return current_user
```

所有需要管理员权限的接口使用 `Depends(require_admin)` 替代硬编码检查。

## 二、用户管理

### API 端点

全部需要 admin 角色，位于 `api/admin.py`。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/admin/users` | 用户列表（分页、按用户名/邮箱搜索） |
| POST | `/admin/users` | 创建用户 |
| PATCH | `/admin/users/{id}` | 编辑用户（角色、状态、显示名） |
| DELETE | `/admin/users/{id}` | 禁用用户（设 `is_active=False`，不物理删除） |
| POST | `/admin/users/{id}/reset-password` | 重置用户密码 |

### 前端页面

- 侧边栏「用户管理」链接改为基于 `user.role == ADMIN` 判断（替换 `username == 'admin'`）
- `templates/admin_users.html`：用户列表页
  - 表格：用户名、邮箱、角色、状态、创建时间、最后登录
  - 搜索：按用户名/邮箱
  - 创建/编辑用户弹窗
  - 重置密码弹窗
  - 禁用/启用用户按钮

## 三、租户管理（管理员视角）

### API 端点

全部需要 admin 角色，位于 `api/admin.py`。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/admin/tenants` | 所有租户列表（分页、按租户名搜索） |
| POST | `/admin/tenants` | 创建租户 |
| DELETE | `/admin/tenants/{id}` | 删除租户（标记删除，异步清理） |
| PATCH | `/admin/tenants/{id}` | 编辑租户配置 |
| POST | `/admin/tenants/{id}/members` | 添加成员 |
| DELETE | `/admin/tenants/{id}/members/{user_id}` | 移除成员 |

### 前端页面

- 侧边栏增加「租户管理」入口（仅 admin 可见）
- 租户列表页：租户名、状态、成员数、API Key 数、创建时间
- 点击租户可展开查看成员列表、API Key 列表
- 按租户名搜索

### 与现有路由的关系

- 现有 `/tenants` 路由不变，普通用户管理自己的租户
- `/admin/tenants` 是管理员全局视角，用 `require_admin` 校验

## 四、API Key 管理（管理员视角）

### API 端点

全部需要 admin 角色，位于 `api/admin.py`。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/admin/api-keys` | 所有 API Key 列表（分页，按租户/用户筛选） |
| DELETE | `/admin/api-keys/{id}` | 撤销指定 API Key |

### 前端展示

- 集成到租户管理页面，展开租户时显示其 API Key 列表
- 独立 API Key 列表页，支持按租户、用户筛选
- 显示：Key 名称、所属租户、创建者、创建时间、最后使用时间、是否系统 Key

### 与现有路由的关系

- 现有 `/tenants/{id}/api-keys` 路由不变，租户 Owner 管理自己的 Key
- `/admin/api-keys` 是管理员全局视角，只查看和撤销，不创建

## 五、审计日志

### 数据模型

```python
class AuditLog(Base):
    id: UUID
    user_id: UUID          # 操作者
    action: String         # 操作类型（user.create, tenant.delete, api_key.revoke 等）
    resource_type: String  # 资源类型（user, tenant, api_key）
    resource_id: String    # 资源 ID
    detail: JSON           # 操作详情
    ip_address: String     # 请求 IP
    created_at: timestamp
```

### 记录时机

- 用户管理：创建、编辑、禁用/启用、重置密码
- 租户管理：创建、编辑、删除、成员变更
- API Key 管理：撤销

### API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/admin/audit-logs` | 审计日志列表（分页，按操作者/操作类型/时间范围筛选） |

### 前端页面

- 侧边栏增加「审计日志」入口（仅 admin 可见）
- 日志列表页：时间、操作者、操作类型、资源、IP、详情
- 按时间范围、操作类型筛选

### 实现方式

- 在 admin API 路由中，每个写操作完成后调用 `log_audit()` 辅助函数
- 直接在业务逻辑中记录，不用信号/事件系统

## 文件变更概览

| 文件 | 变更 |
|------|------|
| `models/user.py` | 添加 `role` 字段和 `UserRole` 枚举 |
| `models/audit_log.py` | 新增 AuditLog 模型 |
| `models/__init__.y` | 导出新模型 |
| `auth/dependencies.py` | 新增 `require_admin` 依赖 |
| `api/admin.py` | 新增所有 admin 端点 |
| `api/auth.py` | 替换 `username == "admin"` 为角色检查 |
| `api/api_keys.py` | 替换硬编码 admin 检查 |
| `migrations/` | 新增迁移（role 字段 + audit_logs 表） |
| `templates/admin_users.html` | 新增用户管理页 |
| `templates/admin_tenants.html` | 新增租户管理页 |
| `templates/admin_api_keys.html` | 新增 API Key 管理页 |
| `templates/admin_audit_logs.html` | 新增审计日志页 |
| `templates/dashboard.html` | 侧边栏改为基于角色判断 |
