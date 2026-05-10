# 用户密码管理系统设计

**日期**: 2026-05-10
**作者**: Claude Code
**状态**: 设计阶段

## 1. 概述

为 Hindsight Manager 添加完整的用户密码管理系统，支持团队协作（多对多用户-租户关系）。

### 1.1 需求背景

当前系统只有 API Key 认证，缺乏面向最终用户的账号管理功能。需要添加：
- 用户账号管理（注册、登录、密码管理）
- 邮箱管理
- 用户与租户的多对多关系
- 两级权限控制（Owner/Member）

### 1.2 核心功能

1. **用户认证**
   - 登录（用户名/密码 + 滑动验证码）
   - 登出
   - JWT Token 管理

2. **密码管理**
   - 修改密码（验证旧密码）
   - 重置密码（邮箱验证码）
   - 密码强度要求（8位+大小写+数字+特殊字符）

3. **邮箱管理**
   - 设置邮箱（首次直接保存）
   - 修改邮箱（验证新邮箱）

4. **用户管理**
   - 管理员创建用户
   - 用户列表和详情查看
   - 用户与租户关联管理

5. **权限控制**
   - Owner: 完全控制（创建/删除 API keys、邀请/移除用户、修改租户配置、删除租户）
   - Member: 只读权限（查看数据、调用 API、查看配置，不能修改任何设置）

## 2. 系统架构

### 2.1 架构选择

采用 **方案 C**: 在 hindsight-manager 中实现全部逻辑。

**理由**:
- 所有用户相关功能集中在一个服务
- 实现简单直接
- hindsight-api 只负责根据 API key 返回 tenant 信息

### 2.2 架构图

```
┌─────────────────┐
│  Browser (UI)   │
│   (Jinja2)      │
└────────┬────────┘
         │ HTTP
         ▼
┌─────────────────────────────────┐
│   hindsight-manager             │
│  ┌──────────────────────────┐   │
│  │  FastAPI Routes          │   │
│  │  - /api/auth/*           │   │
│  │  - /api/users/*          │   │
│  │  - /api/tenants/*        │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │  Business Logic          │   │
│  │  - Auth Service          │   │
│  │  - User Service          │   │
│  │  - Email Service         │   │
│  └──────────────────────────┘   │
└────────┬────────────────────────┘
         │ asyncpg
         ▼
┌─────────────────────────────────┐
│   PostgreSQL                    │
│  ┌──────────────────────────┐   │
│  │  manager schema          │   │
│  │  - users                 │   │
│  │  - user_tenant_roles     │   │
│  │  - tenants (existing)    │   │
│  │  - api_keys (existing)   │   │
│  │  - email_verification_*  │   │
│  │  - login_history         │   │
│  └──────────────────────────┘   │
└─────────────────────────────────┘
```

### 2.3 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 模板引擎 | Jinja2 |
| 密码哈希 | passlib + bcrypt |
| JWT | python-jose |
| 数据库 | asyncpg (PostgreSQL) |
| 邮件 | smtplib / SendGrid API |
| 验证码 | PIL (滑动拼图) |

## 3. 数据库设计

### 3.1 表结构

```sql
-- 用户表
CREATE TABLE manager.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_login_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_users_username ON manager.users(username);
CREATE INDEX idx_users_email ON manager.users(email);

-- 用户-租户关联表（多对多）
CREATE TABLE manager.user_tenant_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES manager.users(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES manager.tenants(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'MEMBER')),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, tenant_id)
);

CREATE INDEX idx_user_tenant_roles_user_id ON manager.user_tenant_roles(user_id);
CREATE INDEX idx_user_tenant_roles_tenant_id ON manager.user_tenant_roles(tenant_id);

-- 邮箱验证码表
CREATE TABLE manager.email_verification_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES manager.users(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('RESET_PASSWORD', 'VERIFY_EMAIL')),
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_email_verification_codes_user_id ON manager.email_verification_codes(user_id);
CREATE INDEX idx_email_verification_codes_expires_at ON manager.email_verification_codes(expires_at);

-- 登录历史表
CREATE TABLE manager.login_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES manager.users(id) ON DELETE CASCADE,
    ip_address TEXT,
    user_agent TEXT,
    success BOOLEAN NOT NULL,
    failed_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_login_history_user_id ON manager.login_history(user_id);
CREATE INDEX idx_login_history_created_at ON manager.login_history(created_at DESC);
```

### 3.2 ER 图

```
┌──────────────┐         ┌─────────────────────┐
│    users     │         │      tenants        │
├──────────────┤         ├─────────────────────┤
│ id (PK)      │         │ id (PK)             │
│ username     │         │ schema_name         │
│ email        │         │ status              │
│ password_hash│         │ config (JSONB)      │
│ ...          │         └─────────────────────┘
└──────────────┘
       │
       │
       ▼
┌─────────────────────┐
│  user_tenant_roles  │
├─────────────────────┤
│ id (PK)             │
│ user_id (FK)        │───► users.id
│ tenant_id (FK)      │───► tenants.id
│ role (OWNER/MEMBER) │
└─────────────────────┘
```

## 4. API 设计

### 4.1 认证相关 API

#### POST /api/auth/login
用户登录

**请求**:
```json
{
  "username": "admin",
  "password": "SecurePass123!",
  "captcha_token": "..."  // 滑动验证码验证通过后的 token
}
```

**响应** (200):
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "username": "admin",
    "email": "admin@example.com"
  }
}
```

#### POST /api/auth/logout
用户登出

**响应** (200):
```json
{
  "message": "Logged out successfully"
}
```

#### GET /api/auth/me
获取当前用户信息

**响应** (200):
```json
{
  "id": "uuid",
  "username": "admin",
  "email": "admin@example.com",
  "tenants": [
    {
      "id": "tenant-1",
      "role": "OWNER"
    }
  ]
}
```

### 4.2 密码管理 API

#### POST /api/auth/change-password
修改密码

**请求**:
```json
{
  "old_password": "OldPass123!",
  "new_password": "NewPass123!"
}
```

**响应** (200):
```json
{
  "message": "Password changed successfully"
}
```

#### POST /api/auth/reset-password/request
请求重置密码（发送验证码）

**请求**:
```json
{
  "email": "user@example.com"
}
```

**响应** (200):
```json
{
  "message": "Verification code sent to your email"
}
```

#### POST /api/auth/reset-password/confirm
确认重置密码

**请求**:
```json
{
  "email": "user@example.com",
  "code": "123456",
  "new_password": "NewPass123!"
}
```

**响应** (200):
```json
{
  "message": "Password reset successfully"
}
```

### 4.3 邮箱管理 API

#### POST /api/auth/email/change
修改邮箱（发送验证码）

**请求**:
```json
{
  "new_email": "newemail@example.com"
}
```

**响应** (200):
```json
{
  "message": "Verification code sent to new email"
}
```

#### POST /api/auth/email/verify
验证新邮箱

**请求**:
```json
{
  "new_email": "newemail@example.com",
  "code": "123456"
}
```

**响应** (200):
```json
{
  "message": "Email updated successfully"
}
```

### 4.4 用户管理 API (管理员)

#### GET /api/users
列出所有用户

**响应** (200):
```json
{
  "users": [
    {
      "id": "uuid",
      "username": "admin",
      "email": "admin@example.com",
      "is_active": true,
      "created_at": "2026-05-10T00:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### POST /api/users
创建新用户

**请求**:
```json
{
  "username": "newuser",
  "email": "newuser@example.com",
  "password": "InitialPass123!",
  "tenant_id": "tenant-1",
  "role": "MEMBER"
}
```

**响应** (201):
```json
{
  "id": "uuid",
  "username": "newuser",
  "email": "newuser@example.com",
  "message": "User created successfully"
}
```

#### PUT /api/users/{user_id}
更新用户信息

**请求**:
```json
{
  "email": "updated@example.com",
  "is_active": false
}
```

#### DELETE /api/users/{user_id}
删除用户

**响应** (200):
```json
{
  "message": "User deleted successfully"
}
```

## 5. UI 设计

### 5.1 页面列表

| 路径 | 页面 | 认证要求 |
|------|------|----------|
| `/login` | 登录页 | 否 |
| `/reset-password` | 重置密码 | 否 |
| `/dashboard` | 用户主页 | 是 |
| `/change-password` | 修改密码 | 是 |
| `/change-email` | 修改邮箱 | 是 |
| `/profile` | 个人资料 | 是 |
| `/admin/users` | 用户列表 | Admin |
| `/admin/users/new` | 创建用户 | Admin |
| `/admin/users/{id}` | 用户详情 | Admin |

### 5.2 登录页面

**组件**:
- 用户名输入框
- 密码输入框
- 滑动验证码组件
- 登录按钮
- "忘记密码" 链接

### 5.3 滑动验证码设计

**实现方式**:
1. 服务端生成 300x150px 背景图，随机位置生成 50x50px 缺口
2. 生成对应的 50x50px 滑块拼图块
3. 前端拖动滑块到认为正确的位置
4. 提交滑块最终 X 坐标到服务端
5. 服务端验证：|提交坐标 - 实际坐标| ≤ 5px 即为通过

**数据结构**:
```json
{
  "captcha_id": "uuid",
  "background_image": "base64_encoded_image",
  "puzzle_image": "base64_encoded_image",
  "puzzle_position": {"x": 120, "y": 30}  // 不返回给前端，仅用于服务端验证
}
```

**安全措施**:
- 验证码 5 分钟有效
- 每次生成新的随机图
- 服务端验证，防止绕过
- 每个 captcha_id 只能验证一次

## 6. 安全设计

### 6.1 密码安全

| 措施 | 实现 |
|------|------|
| 哈希算法 | bcrypt |
| Salt rounds | 12 |
| 最小长度 | 8 位 |
| 复杂度要求 | 大小写 + 数字 + 特殊字符 |
| 常见密码检查 | 禁止使用常见弱密码 |

### 6.2 会话管理

| 措施 | 实现 |
|------|------|
| Token 类型 | JWT (httpOnly cookie) |
| Token 有效期 | 24 小时 |
| 登出机制 | 客户端清除 cookie（服务端不维护黑名单）|

### 6.3 防暴力破解

| 措施 | 实现 |
|------|------|
| 登录失败锁定 | 5 次失败锁定 15 分钟 |
| IP 限流 | 每分钟最多 10 次尝试 |
| 验证码 | 每次登录都需要 |

### 6.4 邮箱验证码

| 措施 | 实现 |
|------|------|
| 验证码长度 | 6 位数字 |
| 有效期 | 5 分钟 |
| 使用次数 | 1 次 |
| 限流 | 每邮箱每天最多 3 次 |

## 7. 数据流

### 7.1 登录流程

```
用户                浏览器               Manager             PostgreSQL
 │                   │                    │                    │
 ├─输入凭据─────────►│                    │                    │
 │                   ├─POST /api/auth/login─────────────►     │
 │                   │                    ├─查询用户─────────►│
 │                   │                    │◄──用户信息────────┤
 │                   │                    ├─验证密码          │
 │                   │                    ├─生成 JWT          │
 │                   │◄──返回 token + 用户─┤                    │
 ├─设置 cookie─────►│                    │                    │
 ├─跳转 dashboard──►│                    │                    │
 │                   │                    │                    │
```

### 7.2 重置密码流程

```
用户                浏览器               Manager             邮件服务
 │                   │                    │                    │
 ├─请求重置─────────►│                    │                    │
 │                   ├─POST /reset-password/request────────►
 │                   │                    ├─生成验证码         │
 │                   │                    ├─保存到数据库       │
 │                   │                    ├─发送邮件─────────►│
 │                   │◄─提示查收──────────┤                    │
 │                                          │                    │
 ├─输入验证码───────►│                    │                    │
 │                   ├─POST /reset-password/confirm────────►
 │                   │                    ├─验证验证码         │
 │                   │                    ├─更新密码           │
 │                   │◄─成功提示──────────┤                    │
 │                                          │                    │
```

## 8. 实现计划

### 8.1 Phase 1: 数据库和基础模型
1. 创建数据库迁移脚本
2. 定义 SQLAlchemy 模型
3. 编写模型测试

### 8.2 Phase 2: 认证服务
1. 实现 JWT token 生成和验证
2. 实现密码哈希和验证
3. 实现登录/登出逻辑
4. 编写认证测试

### 8.3 Phase 3: 密码管理
1. 实现修改密码 API
2. 实现重置密码流程
3. 实现邮箱服务集成
4. 编写密码管理测试

### 8.4 Phase 4: 邮箱管理
1. 实现邮箱修改 API
2. 实现邮箱验证流程
3. 编写邮箱管理测试

### 8.5 Phase 5: 用户管理 API
1. 实现用户 CRUD API
2. 实现用户-租户关联 API
3. 实现权限检查中间件
4. 编写 API 测试

### 8.6 Phase 6: 滑动验证码
1. 实现验证码生成服务
2. 实现验证码验证逻辑
3. 编写验证码测试

### 8.7 Phase 7: UI 实现
1. 实现登录页面
2. 实现密码管理页面
3. 实现邮箱管理页面
4. 实现用户管理页面（管理员）
5. 实现 API 中间件和认证装饰器

### 8.8 Phase 8: 集成测试
1. 端到端测试
2. 安全测试
3. 性能测试

## 9. 依赖服务

### 9.1 邮件服务

**选项 A: SMTP**
- 使用企业 SMTP 服务器
- 配置: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`

**选项 B: SendGrid**
- 使用 SendGrid API
- 配置: `SENDGRID_API_KEY`

### 9.2 环境变量

```bash
# JWT
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# 邮件
EMAIL_SERVICE=smtp  # 或 sendgrid
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=your-password
SMTP_FROM=noreply@example.com

# 验证码
VERIFICATION_CODE_EXPIRE_MINUTES=5
VERIFICATION_CODE_MAX_ATTEMPTS=3

# 密码
PASSWORD_MIN_LENGTH=8
PASSWORD_BCRYPT_ROUNDS=12

# 限流
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
RATE_LIMIT_PER_MINUTE=10
```

## 10. 测试策略

### 10.1 单元测试
- 密码哈希和验证
- JWT 生成和解析
- 验证码生成和验证
- 邮箱验证码验证逻辑

### 10.2 集成测试
- 完整登录流程
- 密码修改流程
- 密码重置流程
- 邮箱修改流程
- 用户 CRUD 操作

### 10.3 端到端测试
- 用户注册到登录的完整流程
- 管理员创建用户流程
- 用户加入租户流程

## 11. 后续扩展

### 11.1 可能的未来功能
- 双因素认证 (2FA/TOTP)
- OAuth 第三方登录 (Google, GitHub)
- 单点登录 (SSO)
- 审计日志
- 细粒度权限控制
- 用户组管理

### 11.2 性能优化
- Redis 缓存用户会话
- 数据库连接池优化
- 邮件发送队列

## 12. 风险和注意事项

### 12.1 安全风险
- **密码泄露**: 使用 bcrypt 哈希，禁止明文存储
- **会话劫持**: 使用 httpOnly cookie + HTTPS
- **CSRF**: 实施 CSRF token 验证
- **重放攻击**: 验证码一次性使用

### 12.2 实现风险
- **邮件发送失败**: 实现重试机制和降级方案
- **验证码被破解**: 使用足够强的随机数生成器
- **数据库迁移**: 充分测试迁移脚本

## 13. 参考资料

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [FastAPI Security Tutorial](https://fastapi.tiangolo.com/tutorial/security/)
