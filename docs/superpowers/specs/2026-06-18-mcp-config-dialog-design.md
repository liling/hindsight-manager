# MCP 配置弹窗设计

**日期**：2026-06-18
**作者**：Ling Li
**状态**：待审核

## 背景与动机

Hindsight Manager 控制台 (`/dashboard`) 顶部 `.usage-guide` 块当前以纯文本展示 MCP 地址，用户复制后需要自己拼接到不同 Harness 框架（Claude Code、OpenCode、Trae Solo）的配置文件中——字段名、外层 key、transport type 因框架而异，容易出错。

本设计将静态 MCP 地址行替换为一个按钮，点击后弹出弹窗，按框架一键生成可直接复制的 MCP 配置 JSON。

## 目标与非目标

### 目标

- 替换 dashboard 顶部 MCP 地址行为"获取 MCP 配置"按钮
- 弹窗支持 Claude Code、OpenCode、Trae Solo 三个框架，tab 切换
- 配置里 `url` 字段已填实际 MCP 地址，方便直接复制使用

### 非目标

- **不**自动注入或生成 API Key。配置里的 `Authorization` 字段使用占位符 `<YOUR_API_KEY>`，让用户自己替换。原因：API Key 是 per-tenant 的，自动注入会引入解密展示、新建/复用策略等复杂度；占位符方案保持 MCP 配置为全局纯模板，不绑定 tenant。
- **不**改动后端任何路由、模型、加密逻辑
- **不**支持"一键应用"（自动写入 `~/.claude.json` 等）——只做"展示 + 复制"

## 用户流程

1. 用户在 `/dashboard` 看到顶部按钮"获取 MCP 配置"
2. 点击 → 弹窗打开
3. 弹窗顶部：MCP 地址 + 复制按钮
4. 中间：3 个 tab（默认 Claude Code），切 tab 换 JSON
5. 右上角"复制" → 复制当前 tab 的 JSON
6. 底部小字提示："将 `<YOUR_API_KEY>` 替换为你的 API Key，可在 API Keys 页面创建"
7. 关闭弹窗

入口与 tenant 无关。没有 tenant 的用户也能用此按钮。

## 三个框架的配置模板

`<MCP_URL>` 在前端渲染时替换为实际 `mcp_url`；`<YOUR_API_KEY>` 保留为字面量占位符。服务名统一叫 `hindsight`。

### Claude Code（写到 `~/.claude.json` 或项目 `.mcp.json`）

```json
{
  "mcpServers": {
    "hindsight": {
      "type": "http",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}
```

### OpenCode（写到 `opencode.json`）

```json
{
  "mcp": {
    "hindsight": {
      "type": "remote",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}
```

### Trae Solo（在 Trae IDE 的 MCP 设置里导入）

```json
{
  "mcpServers": {
    "hindsight": {
      "type": "http",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}
```

Trae 和 Claude Code 的 JSON 结构相同（`mcpServers` + `type:http`），但写入位置不同；OpenCode 用 `mcp` 顶层 key 和 `type:remote`。每个 tab 下方加一行小字注明写入位置。

## UI 布局

```
┌─ MCP 配置 ────────────────────────────┐
│ MCP 地址  https://.../mcp       [复制] │
├────────────────────────────────────────┤
│ [Claude Code][OpenCode][Trae Solo]     │
├────────────────────────────────────────┤
│ {                                      │
│   "mcpServers": {                      │
│     "hindsight": {                     │
│       "type": "http",                  │
│       "url": "https://.../mcp",        │
│       "headers": {                     │
│         "Authorization":               │
│           "Bearer <YOUR_API_KEY>"      │
│       }                                │
│     }                                  │
│   }                                    │
│ }                                  [复制]│
├────────────────────────────────────────┤
│ 写入位置：~/.claude.json 或 .mcp.json   │
│ ⓘ 将 <YOUR_API_KEY> 替换为你的 API Key │
├────────────────────────────────────────┤
│              [关闭]                     │
└────────────────────────────────────────┘
```

## 前端实现细节

### `hindsight_manager/templates/dashboard.html`

1. **删除**：第 16-22 行（`{% if mcp_url %}...{% endif %}` 整段 MCP 地址行）
2. **插入**：在原位置加按钮
   ```html
   <div class="usage-guide-item">
       <span class="usage-guide-label">MCP</span>
       <button class="btn btn-secondary btn-sm" onclick="showMcpConfigModal()">获取 MCP 配置</button>
   </div>
   ```
3. **追加弹窗**：在 `apikey-modal` 之后插入 `mcp-config-modal`（结构对齐现有 `apikey-modal` 的 `modal-backdrop` + `modal-content` 模式，点背景或关闭按钮均可关）：
   - 顶部：MCP 地址行 + 复制按钮
   - tab 栏：3 个按钮
   - `<pre><code id="mcp-config-code">` 显示当前 tab JSON
   - 右上角复制按钮
   - 写入位置提示行（随 tab 变化）
   - 占位符替换提示行（含到 `/api-keys` 页面的链接）
   - 底部"关闭"按钮（`onclick="hideMcpConfigModal()"`）
4. **注入 MCP URL**：在 `<script src="/static/app.js"></script>` 之前加：
   ```html
   <script>window.MCP_URL = "{{ mcp_url }}";</script>
   ```

### `hindsight_manager/static/app.js`

新增 4 个函数 + 3 个模板常量：

```javascript
const MCP_TEMPLATES = {
  "claude": {
    json: `{ "mcpServers": { "hindsight": { "type": "http", "url": "<MCP_URL>", "headers": { "Authorization": "Bearer <YOUR_API_KEY>" } } } }`,
    location: "写入位置：~/.claude.json 或项目 .mcp.json",
  },
  "opencode": {
    json: `{ "mcp": { "hindsight": { "type": "remote", "url": "<MCP_URL>", "headers": { "Authorization": "Bearer <YOUR_API_KEY>" } } } }`,
    location: "写入位置：opencode.json",
  },
  "trae": {
    json: `{ "mcpServers": { "hindsight": { "type": "http", "url": "<MCP_URL>", "headers": { "Authorization": "Bearer <YOUR_API_KEY>" } } } }`,
    location: "写入位置：Trae IDE → 设置 → MCP → 导入",
  },
};

function showMcpConfigModal() { /* 打开弹窗，默认 claude tab */ }
function hideMcpConfigModal() { /* 关闭弹窗 */ }
function switchMcpTab(framework) { /* 切 tab，渲染 JSON + 写入位置 */ }
function getMcpConfigJson(framework) { /* 替换 <MCP_URL> 后返回 JSON 字符串 */ }
```

JSON 显示时格式化（2 空格缩进），方便阅读。复用现有 `copyKey()` 复制。

### 不改动

- `hindsight_manager/api/pages.py`（已传 `mcp_url`）
- 任何后端路由、模型、加密、CSS
- 现有 API Keys 弹窗逻辑

## 测试

纯前端改动，无后端逻辑变化。

### 手动验证清单

1. `uvicorn hindsight_manager.main:app --reload --port 8001` 启动
2. 登录到 `/dashboard`
3. 顶部 `.usage-guide`：API 地址行还在、原 MCP 地址行已消失、"获取 MCP 配置"按钮可见
4. 点按钮 → 弹窗打开，MCP 地址正确，默认 Claude Code tab 高亮
5. 三个 tab 切换：JSON 内容正确变化（`mcpServers`/`mcp`、`http`/`remote`）
6. 复制按钮：MCP 地址、当前 tab JSON 都能复制到剪贴板
7. 占位符 `<YOUR_API_KEY>` 在三个 tab 里都保留为字面量
8. 弹窗关闭后再打开，状态重置回 Claude Code tab
9. 没有 tenant 的用户也能用此按钮（不依赖 tenant）

### 自动化测试

- `pages.py` 未改逻辑，运行 `uv run pytest tests/` 确认无回归
- 纯 HTML/JS 改动，不新增 pytest 用例

## 风险与权衡

| 风险 | 缓解 |
|---|---|
| 三框架的字段名/格式未来变化 | 模板集中在前端 3 个常量里，单点修改 |
| 用户误以为占位符是真 key | 底部明确提示"将 `<YOUR_API_KEY>` 替换为你的 API Key"，并在提示里链接到 API Keys 页面 |
| Trae 和 Claude Code 的 JSON 看起来一样，用户复制错 tab | 每个 tab 下方独立"写入位置"提示，且 tab 高亮明显 |

## 范围外（未来可加）

- 更多框架：Cursor、Cline、Windsurf、VS Code（GitHub Copilot）等。结构相似，加一个 tab 即可。
- 一键应用：自动写入 `~/.claude.json` 等本地文件——需要桌面端或浏览器扩展，超出本设计。
- 自动注入 api_key：日后若有强需求，可在弹窗里加"选择 API Key"下拉，后端解密返回——但需评估安全影响。
