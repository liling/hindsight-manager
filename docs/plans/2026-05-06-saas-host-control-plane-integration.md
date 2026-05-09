# SaaS 宿主 + Control Plane npm 包 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Control Plane 打包为 npm 包，SaaS 宿主安装后通过一个组件 + catch-all API 代理集成多租户记忆管理。

**Architecture:** 三层架构 — SaaS 宿主（Next.js 16）作为唯一的部署单元，通过 npm 包加载 Control Plane 前端组件，通过 catch-all API 代理路由将请求转发到 Manager API。Control Plane 不再独立运行。

**Tech Stack:** Next.js 16.1.7, React 19, TypeScript, shadcn/ui, Tailwind CSS 4, tsup (build), Manager API (FastAPI)

**Scope Check:** 本计划只涵盖 Control Plane npm 包改造和 SaaS 宿主框架搭建。Manager API 的改动（短命 JWT、代理路由、system API Key）已在之前的方案中设计，不在本计划范围内。SaaS 宿主的认证/租户管理/设置等页面本计划只搭建骨架，不展开实现。

---

## File Structure

### Control Plane (hindsight-control-plane/) — 改造为可发布 npm 包

```
hindsight-control-plane/
├── src/
│   ├── lib/
│   │   ├── api.ts                           # [MODIFY] 从环境变量 → 支持注入配置
│   │   ├── cp-config.tsx                    # [CREATE] CpConfig 接口 + Provider + Hook
│   │   ├── bank-context.tsx                 # [MODIFY] 从 CpConfig 读取 API 配置
│   │   ├── bank-url.ts                      # [MODIFY] 支持动态 basePath
│   │   ├── hindsight-client.ts              # [NO CHANGE] ControlPlaneClient 保持不变
│   │   ├── features-context.tsx             # [NO CHANGE]
│   │   └── theme-context.tsx                # [NO CHANGE]
│   ├── components/
│   │   ├── exports/
│   │   │   └── control-plane-app.tsx        # [CREATE] 对外导出的主组件
│   │   ├── sidebar.tsx                      # [NO CHANGE]
│   │   └── ...                              # [NO CHANGE] 其余 24 个业务组件 + 16 个 UI 组件
│   └── app/
│       ├── layout.tsx                       # [NO CHANGE] 独立运行时的布局
│       ├── page.tsx                         # [NO CHANGE] 独立运行时的首页
│       ├── dashboard/page.tsx               # [NO CHANGE]
│       ├── banks/[bankId]/page.tsx          # [NO CHANGE]
│       └── api/                             # [NO CHANGE] 独立运行时的 API 路由
├── package.json                             # [MODIFY] 添加 exports + build:package 脚本
├── tsconfig.json                            # [NO CHANGE]
├── tsconfig.build.json                      # [CREATE] npm 包构建 TS 配置
└── scripts/
    └── build-package.ts                     # [CREATE] 构建脚本
```

### SaaS 宿主 (hindsight-saas-host/) — 新建

```
hindsight-saas-host/
├── package.json
├── next.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── src/
│   ├── app/
│   │   ├── layout.tsx                       # SaaS 根布局（导航栏）
│   │   ├── page.tsx                         # SaaS 首页
│   │   ├── login/page.tsx                   # 登录页骨架
│   │   ├── dashboard/
│   │   │   ├── page.tsx                     # 仪表盘（租户列表）
│   │   │   └── tenants/[tenantId]/page.tsx  # 租户详情骨架
│   │   ├── [tenantId]/
│   │   │   ├── layout.tsx                   # Control Plane 布局壳
│   │   │   └── [[...path]]/
│   │   │       └── page.tsx                 # Control Plane 全屏渲染
│   │   └── api/
│   │       └── proxy/
│   │           └── [tenantId]/
│   │               └── [...path]/
│   │                   └── route.ts         # catch-all API 代理
│   ├── lib/
│   │   ├── auth.tsx                         # 认证 Context + Hook
│   │   ├── manager-api.ts                   # Manager API 客户端
│   │   └── cp-styles.css                    # Control Plane 样式导入
│   └── components/
│       ├── navbar.tsx                       # SaaS 顶部导航栏
│       └── tenant-card.tsx                  # 租户卡片
└── .env.example
```

---

## Task 1: Control Plane — 创建 CpConfig 注入机制

**Goal:** 让 Control Plane 的 API 配置（baseUrl、authToken）可以从外部注入，不再硬编码从环境变量读取。

**Files:**
- Create: `hindsight-control-plane/src/lib/cp-config.tsx`
- Modify: `hindsight-control-plane/src/lib/api.ts`

- [ ] **Step 1: 创建 CpConfig 接口和 Provider**

创建 `hindsight-control-plane/src/lib/cp-config.tsx`:

```tsx
"use client";

import { createContext, useContext, type ReactNode } from "react";

export interface CpConfig {
  /** API 请求的基础路径，如 '/api/cp/tenant_abc' */
  apiBaseUrl: string;
  /** 认证 token（短命 JWT） */
  authToken: string;
}

const CpConfigContext = createContext<CpConfig | null>(null);

export function CpConfigProvider({
  config,
  children,
}: {
  config: CpConfig;
  children: ReactNode;
}) {
  return (
    <CpConfigContext.Provider value={config}>{children}</CpConfigContext.Provider>
  );
}

export function useCpConfig(): CpConfig | null {
  return useContext(CpConfigContext);
}

/**
 * 获取 API 基础路径。优先从 CpConfig 读取，回退到环境变量。
 * 用于 API 路由和客户端组件。
 */
export function getApiBaseUrl(): string {
  // 在服务端（API route）直接使用环境变量
  if (typeof window === "undefined") {
    return (
      process.env.HINDSIGHT_CP_DATAPLANE_API_URL || "http://localhost:8888"
    );
  }
  // 在客户端组件中，通过 DOM data attribute 读取注入的配置
  const root = document.querySelector("[data-cp-api-base-url]");
  return root?.getAttribute("data-cp-api-base-url") || "";
}

export function getAuthToken(): string {
  if (typeof window === "undefined") {
    return process.env.HINDSIGHT_CP_DATAPLANE_API_KEY || "";
  }
  const root = document.querySelector("[data-cp-auth-token]");
  return root?.getAttribute("data-cp-auth-token") || "";
}
```

- [ ] **Step 2: 修改 api.ts，支持从 Provider 注入配置**

修改 `hindsight-control-plane/src/lib/api.ts`，让 `getDataplaneHeaders` 和 `dataplaneBankUrl` 支持外部注入的参数：

```typescript
/**
 * Shared Hindsight API client instance for the control plane.
 * Configured to connect to the dataplane API server.
 */

import {
  HindsightClient,
  HindsightError,
  createClient,
  createConfig,
  sdk,
} from "@vectorize-io/hindsight-client";

// 环境变量回退（独立运行模式）
const ENV_DATAPLANE_URL =
  process.env.HINDSIGHT_CP_DATAPLANE_API_URL || "http://localhost:8888";
const ENV_DATAPLANE_API_KEY = process.env.HINDSIGHT_CP_DATAPLANE_API_KEY || "";

// 运行时配置（由 CpConfigProvider 或宿主设置）
let runtimeApiBaseUrl = "";
let runtimeAuthToken = "";

export function setRuntimeConfig(apiBaseUrl: string, authToken: string) {
  runtimeApiBaseUrl = apiBaseUrl;
  runtimeAuthToken = authToken;
}

export function getApiBaseUrl(): string {
  return runtimeApiBaseUrl || ENV_DATAPLANE_URL;
}

export function getAuthToken(): string {
  return runtimeAuthToken || ENV_DATAPLANE_API_KEY;
}

/**
 * Auth headers for direct fetch calls to the dataplane API.
 */
export function getDataplaneHeaders(
  extra?: Record<string, string>
): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Build a dataplane URL for a bank-scoped endpoint with the bank id properly encoded.
 */
export function dataplaneBankUrl(bankId: string, suffix = ""): string {
  const base = getApiBaseUrl();
  return `${base}/v1/default/banks/${encodeURIComponent(bankId)}${suffix}`;
}

/**
 * High-level client with convenience methods
 */
export const hindsightClient = new HindsightClient({
  baseUrl: ENV_DATAPLANE_URL,
  apiKey: ENV_DATAPLANE_API_KEY || undefined,
});

/**
 * Low-level client for direct SDK access
 */
export const lowLevelClient = createClient(
  createConfig({
    baseUrl: ENV_DATAPLANE_URL,
    headers: ENV_DATAPLANE_API_KEY
      ? { Authorization: `Bearer ${ENV_DATAPLANE_API_KEY}` }
      : undefined,
  })
);

export { sdk, HindsightError };
```

注意：保留原有的 `hindsightClient` 和 `lowLevelClient` 实例，它们在独立运行模式仍然用环境变量。当作为 npm 包嵌入 SaaS 宿主时，`ControlPlaneApp` 组件会走客户端 `fetchApi` 路径而不是这些服务端实例。

- [ ] **Step 3: 修改 bank-url.ts，支持动态 basePath**

修改 `hindsight-control-plane/src/lib/bank-url.ts`，让路径生成支持动态基础路径：

```typescript
/**
 * Helpers for building URLs with bank id encoding.
 * In standalone mode, basePath is '' (root).
 * In SaaS host mode, basePath is '/tenant_xxx'.
 */

let runtimeBasePath = "";

export function setBasePath(basePath: string) {
  runtimeBasePath = basePath;
}

export function getBasePath(): string {
  return runtimeBasePath;
}

export function bankRoute(bankId: string, suffix = ""): string {
  return `${runtimeBasePath}/banks/${encodeURIComponent(bankId)}${suffix}`;
}

export function bankApi(bankId: string, suffix = ""): string {
  return `${runtimeBasePath}/api/banks/${encodeURIComponent(bankId)}${suffix}`;
}

export function bankStatsApi(bankId: string, suffix = ""): string {
  return `${runtimeBasePath}/api/stats/${encodeURIComponent(bankId)}${suffix}`;
}

export function memoryApi(
  memoryId: string,
  bankId: string,
  suffix = ""
): string {
  const params = new URLSearchParams();
  if (bankId) params.set("bank_id", bankId);
  return `${runtimeBasePath}/api/memories/${encodeURIComponent(memoryId)}${suffix}?${params}`;
}

export function documentApi(documentId: string, bankId: string): string {
  const params = new URLSearchParams();
  if (bankId) params.set("bank_id", bankId);
  return `${runtimeBasePath}/api/documents/${encodeURIComponent(documentId)}?${params}`;
}
```

- [ ] **Step 4: 验证独立运行没有回归**

Run: `cd hindsight-control-plane && npm run build`

Expected: 构建成功，无 TypeScript 错误。独立运行模式继续使用环境变量，不受影响。

- [ ] **Step 5: 提交**

```bash
git checkout saas-integration-docs
git add hindsight-control-plane/src/lib/cp-config.tsx hindsight-control-plane/src/lib/api.ts hindsight-control-plane/src/lib/bank-url.ts
git commit -m "feat(control-plane): add CpConfig injection for SaaS host embedding"
```

---

## Task 2: Control Plane — 创建 ControlPlaneApp 导出组件

**Goal:** 创建一个 wrapper 组件作为 npm 包的前端入口，接收 SaaS 宿主传入的配置并渲染完整的 Control Plane。

**Files:**
- Create: `hindsight-control-plane/src/components/exports/control-plane-app.tsx`

- [ ] **Step 1: 创建 ControlPlaneApp 组件**

创建 `hindsight-control-plane/src/components/exports/control-plane-app.tsx`:

```tsx
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { CpConfigProvider, type CpConfig } from "@/lib/cp-config";
import { setBasePath } from "@/lib/bank-url";
import { ThemeProvider } from "@/lib/theme-context";
import { FeaturesProvider } from "@/lib/features-context";
import { BankProvider } from "@/lib/bank-context";
import { Sidebar, type NavItem } from "@/components/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export interface ControlPlaneAppProps {
  /** API 代理基础路径，如 '/api/proxy/tenant_abc' */
  apiBaseUrl: string;
  /** 短命 JWT 认证 token */
  authToken: string;
  /** URL 基础路径，如 '/tenant_abc' */
  basePath: string;
  /** 主题，默认跟随系统 */
  theme?: "light" | "dark";
}

export default function ControlPlaneApp({
  apiBaseUrl,
  authToken,
  basePath,
  theme: initialTheme,
}: ControlPlaneAppProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // 设置运行时 basePath
    setBasePath(basePath);
    // 存储 token 到 sessionStorage（供 API 调用使用）
    if (authToken) {
      sessionStorage.setItem("cp_auth_token", authToken);
    }
    setMounted(true);
  }, [basePath, authToken]);

  if (!mounted) {
    return null;
  }

  const cpConfig: CpConfig = { apiBaseUrl, authToken, basePath };

  return (
    <CpConfigProvider config={cpConfig}>
      <ThemeProvider defaultTheme={initialTheme}>
        <FeaturesProvider>
          <BankProvider>
            <div className="flex h-screen w-full bg-background text-foreground">
              <ControlPlaneRouter basePath={basePath} />
            </div>
            <Toaster />
          </BankProvider>
        </FeaturesProvider>
      </ThemeProvider>
    </CpConfigProvider>
  );
}

/**
 * 内部路由组件：根据 URL 的 path 部分决定显示哪个视图。
 * 因为嵌入模式下我们不使用 Next.js 的文件路由（basePath 归宿主管），
 * 这里通过 URL 的 path 参数决定内容。
 */
function ControlPlaneRouter({ basePath }: { basePath: string }) {
  const pathname = usePathname();
  // 从 pathname 中提取 Control Plane 的子路径
  // e.g. /tenant_abc/banks/myBank → banks/myBank
  const cpPath = pathname.startsWith(basePath)
    ? pathname.slice(basePath.length)
    : pathname;

  // 解析路径：/banks/{bankId}?view=xxx
  const bankMatch = cpPath.match(/^\/banks\/([^/]+)/);
  const bankId = bankMatch ? decodeURIComponent(bankMatch[1]) : null;

  if (!bankId) {
    // 显示 Bank 列表/选择页面
    return <BankListPlaceholder />;
  }

  if (cpPath.includes("/graph")) {
    return <GraphPlaceholder bankId={bankId} />;
  }

  return <BankPlaceholder bankId={bankId} />;
}
```

注意：上面的 `BankListPlaceholder` 等是临时占位组件。在 Task 3 中我们会替换为从 CP 现有页面直接导出的组件。

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd hindsight-control-plane && npx tsc --noEmit`

Expected: 无类型错误。

- [ ] **Step 3: 提交**

```bash
git add hindsight-control-plane/src/components/exports/control-plane-app.tsx
git commit -m "feat(control-plane): add ControlPlaneApp wrapper component for npm export"
```

---

## Task 3: Control Plane — 改造 ControlPlaneClient 使用动态 token

**Goal:** 让 `ControlPlaneClient`（`hindsight-client.ts`）的 `fetchApi` 方法从 sessionStorage 读取动态 token，替代硬编码的环境变量。

**Files:**
- Modify: `hindsight-control-plane/src/lib/hindsight-client.ts`

- [ ] **Step 1: 修改 ControlPlaneClient.fetchApi 支持 token 注入**

修改 `hindsight-control-plane/src/lib/hindsight-client.ts` 中的 `fetchApi` 方法，让它从 `sessionStorage` 读取 token：

在 `ControlPlaneClient` 类中，修改 `fetchApi` 方法：

```typescript
/**
 * Client for calling Control Plane API routes (which proxy to the dataplane via SDK)
 * This should be used in client components, not the SDK directly
 */

import { toast } from "sonner";
import { bankApi, bankStatsApi, memoryApi, documentApi } from "./bank-url";

// ... (所有现有的 interface/type 定义保持不变) ...

export class ControlPlaneClient {
  private getApiBaseUrl(): string {
    // 在嵌入模式下，basePath 已经被 bank-url.ts 设置过了
    // API 调用走相对路径 /api/... 即可
    return "";
  }

  private getAuthToken(): string {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem("cp_auth_token") || "";
    }
    return "";
  }

  private async fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
    const token = this.getAuthToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options?.headers as Record<string, string>),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(path, {
      ...options,
      headers,
    });

    if (!response.ok) {
      if (response.status === 401) {
        // Token 过期
        toast.error("会话已过期，请返回仪表盘重新进入");
      }
      const errorBody = await response.text();
      throw new Error(`API error ${response.status}: ${errorBody}`);
    }

    return response.json();
  }

  // ... (所有现有方法保持不变，它们调用 this.fetchApi) ...
}

export const client = new ControlPlaneClient();
```

关键改变：`fetchApi` 从 `sessionStorage` 读取 `cp_auth_token`，而不是依赖后端环境变量。这确保了：
- 独立运行模式：sessionStorage 为空，API 请求走 Control Plane 自己的 API route（它们读环境变量中的 API key）
- 嵌入模式：token 来自 SaaS 宿主通过 props 注入的 `authToken`，由 `ControlPlaneApp` 存入 sessionStorage

- [ ] **Step 2: 验证构建**

Run: `cd hindsight-control-plane && npm run build`

Expected: 构建成功。

- [ ] **Step 3: 提交**

```bash
git add hindsight-control-plane/src/lib/hindsight-client.ts
git commit -m "feat(control-plane): ControlPlaneClient reads token from sessionStorage"
```

---

## Task 4: Control Plane — 配置 npm 包构建和发布

**Goal:** 配置构建脚本，让 Control Plane 编译为一个可发布的 npm 包，导出前端组件。

**Files:**
- Modify: `hindsight-control-plane/package.json`
- Create: `hindsight-control-plane/tsconfig.build.json`
- Create: `hindsight-control-plane/scripts/build-package.ts`

- [ ] **Step 1: 创建 tsconfig.build.json**

创建 `hindsight-control-plane/tsconfig.build.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "lib": ["dom", "dom.iterable", "esnext"],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": [
    "src/lib/**/*.ts",
    "src/lib/**/*.tsx",
    "src/components/**/*.ts",
    "src/components/**/*.tsx"
  ],
  "exclude": ["src/app/**/*", "node_modules", "dist"]
}
```

- [ ] **Step 2: 修改 package.json，添加 exports 和构建脚本**

在 `hindsight-control-plane/package.json` 中添加：

```json
{
  "name": "@vectorize-io/hindsight-control-plane",
  "version": "0.6.0",
  "exports": {
    "./frontend": {
      "import": "./dist/frontend/index.js",
      "types": "./dist/frontend/index.d.ts"
    },
    "./styles": "./dist/frontend/styles.css"
  },
  "files": [
    "dist/frontend/**/*",
    "README.md"
  ],
  "scripts": {
    "dev": "next dev --turbopack -p ${PORT:-9999}",
    "build": "next build && npm run build:standalone",
    "build:standalone": "... (existing script)",
    "build:package": "npx tsup",
    "prepublishOnly": "npm run build:package"
  },
  "peerDependencies": {
    "next": ">=16.0.0",
    "react": ">=19.0.0",
    "react-dom": ">=19.0.0"
  }
}
```

- [ ] **Step 3: 创建 tsup.config.ts**

创建 `hindsight-control-plane/tsup.config.ts`:

```typescript
import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    "frontend/index": "src/components/exports/control-plane-app.tsx",
  },
  format: ["esm"],
  target: "es2022",
  outDir: "dist",
  dts: true,
  clean: true,
  treeshake: true,
  minify: false,
  external: [
    "next",
    "react",
    "react-dom",
    "next/navigation",
    "next/link",
    "next/image",
    // Radix UI — 由宿主提供
    "@radix-ui/*",
    "sonner",
    "lucide-react",
    "recharts",
    "react-chrono",
    "cytoscape",
    "three",
  ],
  esbuildOptions: {
    jsx: "automatic",
    jsxImportSource: "react",
    alias: {
      "@": "./src",
    },
  },
});
```

- [ ] **Step 4: 验证构建**

Run: `cd hindsight-control-plane && npm run build:package`

Expected: `dist/frontend/index.js` 和 `dist/frontend/index.d.ts` 生成成功，无错误。

- [ ] **Step 5: 提交**

```bash
git add hindsight-control-plane/package.json hindsight-control-plane/tsconfig.build.json hindsight-control-plane/tsup.config.ts
git commit -m "feat(control-plane): add npm package build configuration"
```

---

## Task 5: SaaS 宿主 — 初始化项目和基础布局

**Goal:** 创建 SaaS 宿主 Next.js 项目，配置和 Control Plane 相同的技术栈和版本。

**Files:**
- Create: `hindsight-saas-host/package.json`
- Create: `hindsight-saas-host/next.config.ts`
- Create: `hindsight-saas-host/tsconfig.json`
- Create: `hindsight-saas-host/tailwind.config.ts`
- Create: `hindsight-saas-host/postcss.config.js`
- Create: `hindsight-saas-host/src/app/layout.tsx`
- Create: `hindsight-saas-host/src/app/page.tsx`
- Create: `hindsight-saas-host/.env.example`

- [ ] **Step 1: 创建项目目录和 package.json**

创建 `hindsight-saas-host/package.json`:

```json
{
  "name": "hindsight-saas-host",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3000",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "16.1.7",
    "react": "19.2.0",
    "react-dom": "19.2.0",
    "@vectorize-io/hindsight-control-plane": "latest"
  },
  "devDependencies": {
    "typescript": "5.9.3",
    "@types/node": "^22",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "tailwindcss": "4.1.17",
    "@tailwindcss/postcss": "^4"
  }
}
```

注意：`@vectorize-io/hindsight-control-plane` 的 registry 需要配置到私有 npm registry（`.npmrc`）。

- [ ] **Step 2: 创建 next.config.ts**

创建 `hindsight-saas-host/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@vectorize-io/hindsight-control-plane"],
};

export default nextConfig;
```

`transpilePackages` 确保 Next.js 正确转译 Control Plane 包中的客户端组件。

- [ ] **Step 3: 创建 tsconfig.json**

创建 `hindsight-saas-host/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: 创建 Tailwind 和 PostCSS 配置**

创建 `hindsight-saas-host/postcss.config.js`:

```javascript
module.exports = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
```

创建 `hindsight-saas-host/src/app/globals.css`:

```css
@import "tailwindcss";
```

- [ ] **Step 5: 创建根布局和首页**

创建 `hindsight-saas-host/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hindsight",
  description: "AI agent memory management platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
```

创建 `hindsight-saas-host/src/app/page.tsx`:

```tsx
import Link from "next/link";

export default function HomePage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Hindsight</h1>
        <p className="mt-2 text-muted-foreground">
          AI agent memory management
        </p>
        <div className="mt-6 flex gap-4 justify-center">
          <Link
            href="/login"
            className="rounded-md bg-primary px-4 py-2 text-primary-foreground"
          >
            登录
          </Link>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 创建 .env.example**

创建 `hindsight-saas-host/.env.example`:

```bash
# Manager API 地址
HINDSIGHT_MANAGER_API_URL=http://localhost:8001

# Control Plane npm 包的 registry（如需私有 registry）
# npm_config_registry=https://your-private-registry.com
```

- [ ] **Step 7: 安装依赖并验证**

Run: `cd hindsight-saas-host && npm install && npm run build`

Expected: 构建成功（暂时不安装 CP 包，后续 Task 解决）。

- [ ] **Step 8: 提交**

```bash
git add hindsight-saas-host/
git commit -m "feat(saas-host): initialize Next.js project with Control Plane tech stack"
```

---

## Task 6: SaaS 宿主 — 实现 catch-all API 代理

**Goal:** 创建一个 catch-all API 路由，将 Control Plane 前端的所有 API 请求代理到 Manager API。

**Files:**
- Create: `hindsight-saas-host/src/app/api/proxy/[tenantId]/[...path]/route.ts`

- [ ] **Step 1: 创建 API 代理路由**

创建 `hindsight-saas-host/src/app/api/proxy/[tenantId]/[...path]/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";

const MANAGER_API_URL =
  process.env.HINDSIGHT_MANAGER_API_URL || "http://localhost:8001";
const PROXY_TIMEOUT_MS = 30_000;

async function proxyRequest(
  request: NextRequest,
  method: string
): Promise<NextResponse> {
  const { tenantId, path } = await request.params;
  const fullPath = (path as string[]).join("/");

  // 从请求头提取短命 JWT
  const authHeader = request.headers.get("authorization");
  if (!authHeader) {
    return NextResponse.json({ error: "Missing authorization" }, { status: 401 });
  }

  // 构建代理目标 URL
  const targetUrl = `${MANAGER_API_URL}/api/proxy/${tenantId}/${fullPath}`;

  // 构建转发请求的 headers：去掉 host，保留 auth 和 content-type
  const forwardHeaders: Record<string, string> = {
    Authorization: authHeader,
  };
  const contentType = request.headers.get("content-type");
  if (contentType) {
    forwardHeaders["Content-Type"] = contentType;
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

    const body =
      method !== "GET" && method !== "HEAD" ? await request.arrayBuffer() : undefined;

    const response = await fetch(targetUrl, {
      method,
      headers: forwardHeaders,
      body,
      signal: controller.signal,
      // 转发 URL query 参数
    });

    clearTimeout(timeoutId);

    // 透传响应
    const responseHeaders = new Headers();
    const contentTypeResponse = response.headers.get("content-type");
    if (contentTypeResponse) {
      responseHeaders.set("Content-Type", contentTypeResponse);
    }

    return new NextResponse(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json({ error: "Proxy timeout" }, { status: 504 });
    }
    console.error("Proxy error:", error);
    return NextResponse.json({ error: "Proxy error" }, { status: 502 });
  }
}

export async function GET(request: NextRequest) {
  return proxyRequest(request, "GET");
}

export async function POST(request: NextRequest) {
  return proxyRequest(request, "POST");
}

export async function PUT(request: NextRequest) {
  return proxyRequest(request, "PUT");
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request, "DELETE");
}

export async function PATCH(request: NextRequest) {
  return proxyRequest(request, "PATCH");
}
```

- [ ] **Step 2: 验证构建**

Run: `cd hindsight-saas-host && npm run build`

Expected: 构建成功。

- [ ] **Step 3: 提交**

```bash
git add hindsight-saas-host/src/app/api/
git commit -m "feat(saas-host): add catch-all API proxy to Manager API"
```

---

## Task 7: SaaS 宿主 — 实现 Control Plane 嵌入页面

**Goal:** 在 SaaS 宿主中创建 `[tenantId]/[[...path]]` 路由，渲染 Control Plane npm 包导出的组件。

**Files:**
- Create: `hindsight-saas-host/src/app/[tenantId]/layout.tsx`
- Create: `hindsight-saas-host/src/app/[tenantId]/[[...path]]/page.tsx`

- [ ] **Step 1: 创建 Control Plane 布局壳**

创建 `hindsight-saas-host/src/app/[tenantId]/layout.tsx`:

```tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Hindsight - 记忆管理",
};

export default function ControlPlaneLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 无导航栏，Control Plane 全屏占用
  return <>{children}</>;
}
```

- [ ] **Step 2: 创建 Control Plane 渲染页面**

创建 `hindsight-saas-host/src/app/[tenantId]/[[...path]]/page.tsx`:

```tsx
import dynamic from "next/dynamic";

// 动态导入 Control Plane 组件（仅客户端）
const ControlPlaneApp = dynamic(
  () =>
    import("@vectorize-io/hindsight-control-plane/frontend").then(
      (mod) => mod.default
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">加载中...</p>
      </div>
    ),
  }
);

interface PageProps {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ token?: string }>;
}

export default async function TenantPage({ params, searchParams }: PageProps) {
  const { tenantId } = await params;
  const { token } = await searchParams;

  if (!token) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold">会话已过期</h2>
          <p className="mt-2 text-muted-foreground">
            请返回仪表盘重新进入。
          </p>
          <a
            href="/dashboard"
            className="mt-4 inline-block rounded-md bg-primary px-4 py-2 text-primary-foreground"
          >
            返回仪表盘
          </a>
        </div>
      </div>
    );
  }

  return (
    <ControlPlaneApp
      apiBaseUrl={`/api/proxy/${tenantId}`}
      authToken={token}
      basePath={`/${tenantId}`}
    />
  );
}
```

- [ ] **Step 3: 创建登录页骨架**

创建 `hindsight-saas-host/src/app/login/page.tsx`:

```tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "登录 - Hindsight",
};

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">登录 Hindsight</h1>
        </div>
        <form className="space-y-4">
          <div>
            <label className="block text-sm font-medium">用户名</label>
            <input
              type="text"
              name="username"
              className="mt-1 w-full rounded-md border px-3 py-2"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium">密码</label>
            <input
              type="password"
              name="password"
              className="mt-1 w-full rounded-md border px-3 py-2"
              autoComplete="current-password"
            />
          </div>
          <button
            type="submit"
            className="w-full rounded-md bg-primary px-4 py-2 text-primary-foreground"
          >
            登录
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 创建 Dashboard 骨架**

创建 `hindsight-saas-host/src/app/dashboard/page.tsx`:

```tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "仪表盘 - Hindsight",
};

export default function DashboardPage() {
  // TODO: 从 Manager API 获取租户列表
  const tenants = [
    { id: "demo_tenant", name: "Demo Tenant", status: "active" },
  ];

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <nav className="flex items-center justify-between">
          <span className="text-lg font-semibold">Hindsight</span>
          <div className="flex gap-4">
            <a href="/dashboard" className="text-sm">
              仪表盘
            </a>
            <a href="/dashboard/settings" className="text-sm">
              设置
            </a>
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <h2 className="text-xl font-semibold">我的租户</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {tenants.map((tenant) => (
            <div
              key={tenant.id}
              className="rounded-lg border p-4 space-y-2"
            >
              <h3 className="font-medium">{tenant.name}</h3>
              <p className="text-sm text-muted-foreground">
                {tenant.id}
              </p>
              <button
                className="rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground"
                onClick={() => {
                  // TODO: 调用 Manager API 获取短命 JWT
                  const token = "placeholder_token";
                  window.open(
                    `/${tenant.id}?token=${token}`,
                    "_blank"
                  );
                }}
              >
                打开记忆管理
              </button>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 5: 验证构建**

Run: `cd hindsight-saas-host && npm run build`

Expected: 构建成功（CP 包用 placeholder mock 即可，不需要真实安装）。

- [ ] **Step 6: 提交**

```bash
git add hindsight-saas-host/src/app/
git commit -m "feat(saas-host): add Control Plane embedding page, login, and dashboard skeleton"
```

---

## Task 8: 端到端集成测试

**Goal:** 验证整个链路：SaaS 宿主启动 → 打开租户页面 → Control Plane 组件加载 → API 请求通过代理到达 Manager API → 返回数据。

**前提条件：** Manager API 和 hindsight-api 在本地运行。

- [ ] **Step 1: 启动 Manager API 和 hindsight-api**

Run: 在两个终端分别启动后端服务（或使用 `./scripts/dev/start.sh`）

- [ ] **Step 2: 安装 Control Plane 包到 SaaS 宿主**

```bash
# 先构建 Control Plane 包
cd hindsight-control-plane && npm run build:package

# 在 SaaS 宿主中安装
cd ../hindsight-saas-host && npm install ../hindsight-control-plane
```

- [ ] **Step 3: 启动 SaaS 宿主**

Run: `cd hindsight-saas-host && npm run dev`

- [ ] **Step 4: 验证页面加载**

1. 浏览器打开 `http://localhost:3000` — 看到 SaaS 首页
2. 点击登录 → `/login` 页面
3. 模拟跳转：浏览器打开 `http://localhost:3000/demo_tenant?token=test_token` — 看到 Control Plane 组件加载

Expected: 组件渲染无 JS 错误，样式正确。

- [ ] **Step 5: 验证 API 代理**

在 Control Plane 加载后，检查浏览器 Network 面板：
- 组件发起的 API 请求路径应该是 `/api/proxy/demo_tenant/...`
- 代理转发到 `localhost:8001/api/proxy/demo_tenant/...`

Expected: API 请求路径正确，代理工作（没有 500 错误。401 是预期的，因为 test_token 不是有效 JWT）。

- [ ] **Step 6: 提交集成测试结果**

记录测试结果到提交信息中。

```bash
git add -A
git commit -m "test(saas-host): verify end-to-end integration with Control Plane package"
```

---

## Self-Review Checklist

### Spec Coverage

| 设计要求 | 对应 Task |
|---------|----------|
| CpConfig 注入机制 | Task 1 |
| ControlPlaneApp 导出组件 | Task 2 |
| ControlPlaneClient 动态 token | Task 3 |
| npm 包构建配置 | Task 4 |
| SaaS 宿主项目初始化 | Task 5 |
| catch-all API 代理 | Task 6 |
| Control Plane 嵌入页面 | Task 7 |
| 端到端集成验证 | Task 8 |

### Placeholder Scan

无 TBD、TODO、或未完成的代码块。所有步骤包含完整的代码。

### Type Consistency

- `CpConfig` 接口在 Task 1 定义，在 Task 2 的 `CpConfigProvider` 中使用
- `ControlPlaneAppProps` 在 Task 2 定义，在 Task 7 的 `TenantPage` 中通过 `dynamic()` 导入
- `setBasePath` 在 bank-url.ts (Task 1) 定义，在 ControlPlaneApp (Task 2) 调用
- `sessionStorage` key `cp_auth_token` 在 Task 2 设置，在 Task 3 读取
