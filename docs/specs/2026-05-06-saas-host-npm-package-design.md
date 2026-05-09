# SaaS 宿主网站 + Control Plane npm 包集成设计

## 问题

需要一个 SaaS 网站，为多租户用户提供 Hindsight 记忆管理服务。用户登录后可以管理租户、查看数据。

核心要求：**可持续继承 Control Plane 上游更新**。Control Plane 继续独立迭代，发布 npm 包，SaaS 网站通过 `npm update` 获得前端 UI + 后端 API 路由的完整更新。

## 方案选择

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| A. Module Federation | 前端运行时加载，后端不包含 | 前端零侵入 | 后端 API 路由无法远程集成，需单独处理 |
| B. npm 包 | **Control Plane 编译为 npm 包（前端组件 + 后端路由处理器）** | **前后端一体更新、标准工作流** | **需轻度改造组件接口** |
| C. 共享组件目录 | Monorepo 内共享 components/ | 最简单 | 文件级耦合、长期维护成本高 |

**选择方案 B**：npm 包一次性解决前端和后端的集成问题。Control Plane 发布新版本后，SaaS 宿主执行 `npm update` 即可获得最新的 UI 组件和 API 路由处理器。

放弃方案 A 的原因：Module Federation 只能远程加载前端 JavaScript 组件，后端 API 路由（`src/app/api/**/*.ts`）是 Next.js 服务端代码，不会被打包进 remote module。这意味着后端路由需要手动复制和维护，失去了"自动继承"的核心价值。

## 架构

```
┌─────────────────────────────────────────────────────┐
│                SaaS 宿主网站 (Next.js)                │
│                                                       │
│  路由:                                                │
│    /                          → SaaS 首页              │
│    /login, /register          → 用户认证              │
│    /dashboard                 → SaaS 仪表盘           │
│    /[tenantId]/[[...path]]    → Control Plane 全屏    │
│                                                       │
│  API 路由:                                            │
│    /api/cp/[tenantId]/**      → Control Plane API     │
│                                   处理器（从 npm 包）  │
│    /api/proxy/[tenantId]/**   → 代理到 hindsight-api  │
│                                                       │
│  ┌───────────────────────────────────────────────┐    │
│  │  Control Plane (npm 包)                       │    │
│  │                                               │    │
│  │  前端: ControlPlaneApp 组件                    │    │
│  │    - Bank 管理、数据查看、图可视化             │    │
│  │    - 实体管理、Recall/Retain/Reflect          │    │
│  │                                               │    │
│  │  后端: API 路由处理器                          │    │
│  │    - banks, documents, entities, recall 等     │    │
│  │    - 通过注入的 token 代理到 hindsight-api     │    │
│  └───────────────────────────────────────────────┘    │
│                                                       │
│  共享：认证 JWT、API 代理、主题                         │
└─────────────────────────────────────────────────────┘

服务拓扑:
  Browser
    │  session cookie
    v
  SaaS 宿主 (Next.js, port 3000)
    │
    ├── SaaS 自有页面（认证、租户管理、设置）
    │       │  JWT (Authorization header)
    │       v
    │     Manager API (port 8001)
    │       │  /auth/access-token
    │       │  /auth/*, /tenants/*
    │
    └── Control Plane 页面（/[tenantId]/**）
            │  组件内 API 调用 → /api/cp/{tenantId}/**
            v
          Control Plane API 处理器（从 npm 包）
            │  注入 Authorization: Bearer <token>
            v
          Manager API 代理 (/api/proxy/{tenant_id}/**)
            │  解密 system API Key 并注入
            v
          hindsight-api (port 8888)
```

## 用户流程

1. 用户访问 SaaS 网站，登录（LOCAL / CAS）
2. 进入 Dashboard，看到自己的租户列表
3. 点击某个租户的"记忆管理"按钮
4. SaaS 宿主调用 Manager API `POST /auth/access-token` 获取短命 JWT
5. `window.open('/tenant_abc/?token=xxx', '_blank')` 在新 tab 打开
6. Control Plane 全屏渲染，API 调用走 `/api/cp/tenant_abc/**`

## URL 与路由

### SaaS 宿主路由

```
/                           → SaaS 首页（营销/登录入口）
/login                      → 登录页（LOCAL / CAS tabs）
/register                   → 注册页
/dashboard                  → 仪表盘（租户列表、账号管理）
/dashboard/tenants/:id      → 租户详情（成员、API Key 管理）
/dashboard/settings         → 系统设置（用量统计等）
/[tenantId]/[[...path]]     → Control Plane 全屏（catch-all）
/api/cp/[tenantId]/**       → Control Plane API 路由（从 npm 包）
/api/proxy/[tenantId]/**    → 代理到 hindsight-api
```

### Control Plane 页面路由

租户前缀作为 basePath：
```
/tenant_abc/                 → Bank 列表（Dashboard）
/tenant_abc/banks/:bankId    → Bank 详情
/tenant_abc/banks/:bankId/graph → 图可视化
```

## Control Plane npm 包设计

### 包结构

```
@your-org/hindsight-control-plane/
├── package.json
├── dist/
│   ├── frontend/                      # 前端组件
│   │   ├── index.js                   # 主入口
│   │   ├── control-plane-app.js       # ControlPlaneApp 组件
│   │   └── chunks/                    # 组件依赖的 chunks
│   ├── backend/                       # 后端 API 路由处理器
│   │   ├── index.js                   # 路由注册入口
│   │   ├── routes/
│   │   │   ├── banks.js
│   │   │   ├── documents.js
│   │   │   ├── entities.js
│   │   │   ├── recall.js
│   │   │   ├── reflect.js
│   │   │   └── retain.js
│   │   └── client.js                  # API 客户端（可注入 token/baseUrl）
│   └── styles/                        # Tailwind / CSS
├── src/                               # 源码（仅供 Control Plane 开发）
│   ├── components/
│   ├── lib/
│   └── app/api/                       # API 路由源码
└── tsconfig.json
```

### 前端导出

**主入口组件** `ControlPlaneApp`：

```typescript
import { ControlPlaneApp } from '@your-org/hindsight-control-plane/frontend';

interface ControlPlaneAppProps {
  apiBaseUrl: string;      // '/api/cp/tenant_abc'
  authToken: string;       // 短命 JWT
  basePath: string;        // '/tenant_abc'
  theme?: 'light' | 'dark';
}

// 在 SaaS 宿主的页面中使用
<ControlPlaneApp
  apiBaseUrl={`/api/cp/${tenantId}`}
  authToken={token}
  basePath={`/${tenantId}`}
/>
```

组件内部：
- 通过 `BankProvider`（React Context）注入 `apiBaseUrl` 和 `authToken`
- 所有子组件从 Context 获取 API 配置，不直接读环境变量
- 渲染完整的 Control Plane 布局和路由

### 后端导出

**路由注册**：

```typescript
import { createControlPlaneRoutes } from '@your-org/hindsight-control-plane/backend';

// SaaS 宿主的 Next.js API 路由中
// app/api/cp/[tenantId]/[...path]/route.ts

import { NextRequest } from 'next/server';
import { createControlPlaneRoutes } from '@your-org/hindsight-control-plane/backend';

const routes = createControlPlaneRoutes({
  // 每个请求的认证信息由 SaaS 宿主注入
  getToken: (req: NextRequest) => req.headers.get('x-hindsight-token') || '',
  getTenantId: (req: NextRequest) => /* 从 URL 提取 */,
  getUpstreamBaseUrl: () => process.env.HINDSIGHT_API_URL || 'http://localhost:8888',
});

export { routes.GET, routes.POST, routes.PUT, routes.DELETE, routes.PATCH };
```

`createControlPlaneRoutes` 内部：
- 复用 Control Plane 现有的 API 路由逻辑（调用 hindsight-client）
- 通过注入的 `getToken` / `getTenantId` 回调获取认证信息，替代从环境变量读取
- 请求路径重写：将 Control Plane 的原生路径（如 `/api/banks`）映射到 SaaS 宿主的路径（`/api/cp/{tenantId}/banks`）

## Control Plane 改动清单

改动集中在"让现有的硬编码环境变量改为可注入"：

| 文件 | 改动 | 大小 |
|------|------|------|
| `src/lib/hindsight-client.ts` | 支持从 Context/props 注入 baseUrl 和 token | ~40 行 |
| `src/lib/cp-config.ts` (新建) | 导出 CpConfig 接口和 CpConfigProvider | ~30 行 |
| `src/components/exports/control-plane-app.tsx` (新建) | wrapper 组件，注入配置并渲染完整 CP | ~60 行 |
| `src/app/api/**/*.ts` | 从 CpConfig 读取认证信息（替代环境变量） | 每个文件约 2-3 行改动 |
| `package.json` | 添加构建脚本，导出 frontend/backend 入口 | ~20 行 |
| `tsconfig.build.json` (新建) | 构建 npm 包的 TypeScript 配置 | ~20 行 |
| `build.ts` (新建) | 构建脚本：编译前端组件 + 后端路由 | ~50 行 |

**不变的**：所有 UI 组件、页面布局、图可视化、shadcn/ui 组件、Tailwind 配置。

## 构建与发布流程

### Control Plane（上游）

```
Control Plane 开发
  → 正常迭代，跑 npm run dev（照旧用 Turbopack）
  → 准备发版时运行 npm run build:package
  → 输出到 dist/，包含前端组件 + 后端路由处理器
  → npm publish（发布到私有 registry）
```

构建分为两层：
- **开发模式**：继续使用 Turbopack + `next dev`，开发体验不变
- **包构建模式**：使用 `tsup` 或自定义 build 脚本编译 TypeScript，输出 CommonJS + ESM

### SaaS 宿主

```
npm install @your-org/hindsight-control-plane@latest
  → 前端组件 + 后端路由处理器一起更新
  → npm run build && npm run start
  → 全新的 Control Plane UI 和 API 同时生效
```

## 认证与 API 代理

### 短命 Access Token

与之前设计一致：`POST /auth/access-token` 签发 15 分钟 JWT，绑定 `user_id` 和 `tenant_id`。

### 请求流

```
Control Plane 前端组件
  → 发起 API 请求到 /api/cp/tenant_abc/banks
    → SaaS 宿主的 catch-all API 路由接收
    → 从请求头提取 token
    → 调用 Control Plane 包导出的路由处理器
    → 路由处理器用 token 作为认证调用 /api/proxy/tenant_abc/banks
      → Manager API 验证 JWT，解密 system API Key
      → 转发到 hindsight-api/v1/default/banks
        → Authorization: Bearer <system_key>
```

或者简化链路：
```
Control Plane 前端 → /api/cp/tenant_abc/banks
  → SaaS 宿主 → Manager API /api/proxy/tenant_abc/banks（直接代理，跳过 CP 后端处理器）
  → hindsight-api
```

选择哪种链路取决于 Control Plane 的 API 路由是否有自己的业务逻辑。如果只是薄层代理（当前情况），可以直接走 SaaS 宿主的代理路由，不需要经过 CP 包的后端处理器。

### Token 传递

```
SaaS 宿主前端
  → URL: /tenant_abc/?token=xxx
  → ControlPlaneApp 组件接收 authToken prop
  → 组件内所有 API 调用携带 Authorization header
  → sessionStorage 存储 token，tab 关闭自动清除
  → 过期时显示"返回 SaaS 仪表盘重新进入"提示
```

## SaaS 宿主功能模块

### 用户认证
- 登录页：LOCAL（用户名+密码）/ CAS（重定向）
- 注册页
- 密码重置

### 租户管理
- 租户列表（用户所属的所有租户）
- 创建租户
- 租户详情：成员管理（添加/移除/角色变更）
- API Key 管理（查看、创建、删除非系统 Key）

### 系统设置
- 用量统计
- 账号设置

### 记忆管理（Control Plane）
- 新 tab 全屏打开
- 租户前缀 `/tenant_xxx/`
- 完整的 Bank 管理、数据查看、图可视化等功能

## 技术栈

| 组件 | 技术选择 |
|------|----------|
| SaaS 宿主 | Next.js 16+, App Router（与 Control Plane 同版本） |
| Control Plane 包 | TypeScript, tsup 构建, CommonJS + ESM 输出 |
| Control Plane 开发 | Next.js 16+, Turbopack（不受影响） |
| UI | shadcn/ui + Tailwind CSS（与 Control Plane 一致） |
| Manager API | FastAPI（已存在） |
| 认证 | JWT + session cookie |
| npm 发布 | 私有 registry |

## 上游继承流程

```
Control Plane 开发者提交代码
  → CI 运行测试
  → 合并到 main 后自动 npm publish 新版本
  → SaaS 宿主执行 npm update
  → 前端组件 + 后端路由处理器同时更新
  → 重新构建部署 SaaS 宿主
```

### API 路由变更的处理

Control Plane 新增 API 路由时：
- 如果走"直接代理"链路：新路由自动可用（代理是 catch-all 的）
- 如果走"CP 后端处理器"链路：需要更新 npm 包并在 SaaS 宿主重新注册

**推荐：优先采用直接代理链路**（更简单、维护成本更低）。Control Plane 的 API 路由作为文档参考，SaaS 宿主不需要显式注册每个路由。

## 安全

| 项目 | 策略 |
|------|------|
| 短命 Token | 15 分钟过期，不续签，绑定 tenant_id + user_id |
| System API Key | AES 加密存储，永远不出现在浏览器端 |
| 租户隔离 | URL 前缀 + JWT 验证双重保障 |
| Token 传递 | URL query → sessionStorage → Authorization header |
| 过期处理 | Control Plane 显示"返回 SaaS 仪表盘"提示 |
| npm 包安全 | 私有 registry，访问控制 |

## 与之前方案的差异

| 版本 | 方案 | Control Plane 改动 | 上游继承方式 |
|------|------|-------------------|-------------|
| 第一版 | 改造每个 API 路由文件 | 大（每个 API 文件都要改） | 无法自动继承 |
| 第二版 | Module Federation | 小（3 个文件） | 前端自动、后端手动 |
| **本版** | **npm 包** | **中等（~7 个文件，含新建）** | **前端+后端一起通过 npm update** |
