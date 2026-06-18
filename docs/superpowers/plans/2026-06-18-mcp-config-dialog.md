# MCP 配置弹窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 dashboard 顶部静态展示的 MCP 地址行替换为"获取 MCP 配置"按钮，点击后弹出弹窗，按 Claude Code / OpenCode / Trae Solo 三个框架 tab 生成可直接复制的 MCP 配置 JSON（`url` 已填实际地址，`Authorization` 用 `<YOUR_API_KEY>` 占位符）。

**Architecture:** 纯前端改动。`dashboard.html` 加按钮 + 弹窗结构 + `window.MCP_URL` 注入；`static/app.js` 加 3 个模板常量 + 4 个函数。配置不绑 tenant，不自动注入 api_key。

**Tech Stack:** FastAPI（Jinja2 模板）、原生 JavaScript（无前端框架）、pytest + httpx ASGITransport 做页面渲染测试。

## Global Constraints

- 入口位置：替换 `dashboard.html` 第 16-22 行的 `{% if mcp_url %}...{% endif %}` MCP 地址行
- 占位符统一格式：`<YOUR_API_KEY>`（尖括号），在三个框架 tab 里都保留为字面量，**不能**被替换或转义
- 服务名统一：`hindsight`
- 鉴权头格式：`"Authorization": "Bearer <YOUR_API_KEY>"`
- 三框架的字段差异：
  - Claude Code：`mcpServers` + `type: "http"`
  - OpenCode：`mcp` + `type: "remote"`
  - Trae Solo：`mcpServers` + `type: "http"`（与 Claude Code 同结构，仅写入位置不同）
- 不改后端任何路由、模型、加密逻辑；`pages.py` 已传 `mcp_url`，无需改
- 弹窗结构对齐现有 `apikey-modal` 的 `modal-backdrop` + `modal-content` 模式，复用 `.modal.hidden`、`.btn`、`.copy-btn` 等 CSS 类
- 设置 code 内容用 `textContent` 不用 `innerHTML`，避免 `<YOUR_API_KEY>` 被解析为 HTML 标签

---

## File Structure

| 文件 | 改动 | 职责 |
|---|---|---|
| `hindsight_manager/templates/dashboard.html` | 修改 | 删旧 MCP 地址行；加按钮、弹窗 DOM、`window.MCP_URL` 注入 |
| `hindsight_manager/static/app.js` | 修改 | 加 `MCP_TEMPLATES` 常量 + `showMcpConfigModal` / `hideMcpConfigModal` / `switchMcpTab` / `getMcpConfigJson` 4 个函数 |
| `tests/test_pages.py` | 修改 | 扩展 `test_dashboard_page_renders`，断言含新按钮和弹窗元素、不含旧 MCP 地址文本 |

---

### Task 1: 在 dashboard.html 替换 MCP 地址行为按钮 + 弹窗结构（TDD）

**Files:**
- Modify: `tests/test_pages.py:49-67`（扩展 `test_dashboard_page_renders`）
- Modify: `hindsight_manager/templates/dashboard.html:16-22`（删旧 MCP 行）+ 末尾加弹窗 + 注入 `window.MCP_URL`

**Interfaces:**
- Produces: HTML 元素 id `mcp-config-modal`（弹窗根）、`mcp-config-code`（代码框）、`mcp-config-location`（写入位置提示行）、class `mcp-tab` + `data-framework` 属性（tab 按钮）—— 这些 id/class 是 Task 2 的 JS 函数操作的契约，必须严格匹配。

- [ ] **Step 1: 扩展 test_pages.py 加新断言**

打开 `tests/test_pages.py`，找到 `test_dashboard_page_renders`（约 49-67 行），在末尾加断言。修改后完整函数：

```python
@pytest.mark.asyncio
async def test_dashboard_page_renders(client: AsyncClient):
    # The dashboard queries tenants from the DB via session.execute().
    # The default mock session's execute returns an AsyncMock whose .all()
    # is also an AsyncMock (returns a coroutine). We need a proper mock result.
    mock_result = MagicMock()
    mock_result.all.return_value = []  # empty tenant list

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override

    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "记忆库" in resp.text
    # MCP config dialog: new button replaces the old static MCP URL row
    assert "获取 MCP 配置" in resp.text
    assert 'id="mcp-config-modal"' in resp.text
    assert 'id="mcp-config-code"' in resp.text
    assert 'id="mcp-config-location"' in resp.text
    assert "window.MCP_URL" in resp.text
    # Old static MCP URL display row should be gone
    assert ">MCP 地址<" not in resp.text
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run pytest tests/test_pages.py::test_dashboard_page_renders -v`

Expected: FAIL — `AssertionError: assert '获取 MCP 配置' in '<html>...'`（因为 HTML 还没改）

- [ ] **Step 3: 修改 dashboard.html — 删旧 MCP 地址行**

打开 `hindsight_manager/templates/dashboard.html`，删除第 16-22 行整段：

```html
    {% if mcp_url %}
    <div class="usage-guide-item">
        <span class="usage-guide-label">MCP 地址</span>
        <code class="usage-guide-value">{{ mcp_url }}</code>
        <button type="button" class="copy-btn" onclick="copyKey('{{ mcp_url }}')" title="复制"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
    </div>
    {% endif %}
```

替换为：

```html
    <div class="usage-guide-item">
        <span class="usage-guide-label">MCP</span>
        <button type="button" class="btn btn-secondary btn-sm" onclick="showMcpConfigModal()">获取 MCP 配置</button>
    </div>
```

- [ ] **Step 4: 在 dashboard.html 末尾加弹窗 + MCP_URL 注入**

找到文件末尾的 `apikey-modal` 关闭标签（约 108 行 `</div>` 之后），在那之后、`<script src="/static/app.js"></script>` 之前，插入弹窗。修改后该区域完整结构：

```html
    </div>
</div>

<div id="mcp-config-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideMcpConfigModal()"></div>
    <div class="modal-content">
        <h3>MCP 配置</h3>
        <div class="usage-guide-item" style="margin-bottom:12px">
            <code class="usage-guide-value">{{ mcp_url }}</code>
            <button type="button" class="copy-btn" onclick="copyKey('{{ mcp_url }}')" title="复制"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        </div>
        <div class="mcp-tabs" style="display:flex;gap:4px;margin-bottom:12px;border-bottom:1px solid var(--border);">
            <button type="button" class="btn btn-secondary btn-sm mcp-tab" data-framework="claude" onclick="switchMcpTab('claude')">Claude Code</button>
            <button type="button" class="btn btn-secondary btn-sm mcp-tab" data-framework="opencode" onclick="switchMcpTab('opencode')">OpenCode</button>
            <button type="button" class="btn btn-secondary btn-sm mcp-tab" data-framework="trae" onclick="switchMcpTab('trae')">Trae Solo</button>
        </div>
        <div style="position:relative">
            <pre style="background:var(--bg-secondary);padding:12px;border-radius:6px;overflow-x:auto;max-height:320px;margin:0"><code id="mcp-config-code"></code></pre>
            <button type="button" class="copy-btn" onclick="copyKey(document.getElementById('mcp-config-code').textContent)" title="复制" style="position:absolute;top:8px;right:8px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        </div>
        <p id="mcp-config-location" style="font-size:12px;color:var(--text-secondary);margin-top:8px"></p>
        <p style="font-size:12px;color:var(--text-secondary);margin-top:4px">将 <code>&lt;YOUR_API_KEY&gt;</code> 替换为你的 API Key，可在 <a href="/api-keys">API Keys</a> 页面创建。</p>
        <div class="modal-actions">
            <button type="button" class="btn btn-primary" onclick="hideMcpConfigModal()">关闭</button>
        </div>
    </div>
</div>

<script>window.MCP_URL = "{{ mcp_url }}";</script>
<script src="/static/app.js"></script>
{% endblock %}
```

注意：
- `mcp_url` 由 `pages.py:59` 已传入模板上下文，可直接 `{{ mcp_url }}`
- `<code>&lt;YOUR_API_KEY&gt;</code>` 必须 HTML 转义（`<` → `&lt;`，`>` → `&gt;`），否则浏览器解析为标签
- 末尾原本只有一行 `<script src="/static/app.js"></script>`，现在前面多一行 `window.MCP_URL` 注入

- [ ] **Step 5: 运行测试，确认通过**

Run: `uv run pytest tests/test_pages.py::test_dashboard_page_renders -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_pages.py hindsight_manager/templates/dashboard.html
git commit -m "$(cat <<'EOF'
feat: add MCP config dialog button and modal structure on dashboard

Replace the static MCP URL row with a button that opens a modal showing
framework-specific MCP configs (Claude Code / OpenCode / Trae Solo).
API key is left as a placeholder for the user to fill in.
EOF
)"
```

---

### Task 2: 在 app.js 加 MCP 配置的 JS 逻辑

**Files:**
- Modify: `hindsight_manager/static/app.js`（在文件末尾追加，约 233 行后）

**Interfaces:**
- Consumes: Task 1 产出的 DOM 元素 id（`mcp-config-modal`、`mcp-config-code`、`mcp-config-location`）、class `mcp-tab` + `data-framework` 属性、全局 `window.MCP_URL`
- Produces: 4 个全局函数 `showMcpConfigModal` / `hideMcpConfigModal` / `switchMcpTab` / `getMcpConfigJson` —— 由 Task 1 的 `onclick=` 属性调用

- [ ] **Step 1: 在 app.js 末尾追加 MCP 配置代码**

打开 `hindsight_manager/static/app.js`，在文件末尾（`copyKey` 函数闭合的 `}` 之后）追加：

```javascript

const MCP_TEMPLATES = {
  claude: {
    json: `{
  "mcpServers": {
    "hindsight": {
      "type": "http",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}`,
    location: "写入位置：~/.claude.json 或项目 .mcp.json",
  },
  opencode: {
    json: `{
  "mcp": {
    "hindsight": {
      "type": "remote",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}`,
    location: "写入位置：opencode.json",
  },
  trae: {
    json: `{
  "mcpServers": {
    "hindsight": {
      "type": "http",
      "url": "<MCP_URL>",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}`,
    location: "写入位置：Trae IDE → 设置 → MCP → 导入",
  },
};

function showMcpConfigModal() {
  switchMcpTab("claude");
  document.getElementById("mcp-config-modal").classList.remove("hidden");
}

function hideMcpConfigModal() {
  document.getElementById("mcp-config-modal").classList.add("hidden");
}

function switchMcpTab(framework) {
  document.querySelectorAll(".mcp-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.framework === framework);
  });
  const code = document.getElementById("mcp-config-code");
  const loc = document.getElementById("mcp-config-location");
  if (!code || !loc) return;
  code.textContent = getMcpConfigJson(framework);
  loc.textContent = MCP_TEMPLATES[framework]?.location || "";
}

function getMcpConfigJson(framework) {
  const tpl = MCP_TEMPLATES[framework];
  if (!tpl) return "";
  return tpl.json.replaceAll("<MCP_URL>", window.MCP_URL || "");
}
```

关键点：
- 模板里 `<MCP_URL>` 在 `getMcpConfigJson` 里被实际地址替换；`<YOUR_API_KEY>` 保留字面量
- `code.textContent = ...` 用 textContent 而非 innerHTML，确保 `<YOUR_API_KEY>` 显示为字面文本而非被解析为 HTML 标签
- `replaceAll` 需要现代浏览器（Chrome 85+ / Firefox 77+ / Safari 14+），管理后台场景可接受

- [ ] **Step 2: 启动 dev server 做首次端到端验证**

启动服务（在项目根目录）：

```bash
uv run uvicorn hindsight_manager.main:app --reload --port 8001
```

在浏览器打开 http://localhost:8001/dashboard（需先登录）。验证：
- 顶部 `.usage-guide` 块：API 地址行还在、原 MCP 地址行已消失、新增"获取 MCP 配置"按钮可见
- 点"获取 MCP 配置" → 弹窗打开
- 默认 Claude Code tab 高亮，代码框显示 JSON，`url` 字段是实际地址
- 切到 OpenCode：JSON 变为 `mcp` + `type: "remote"`
- 切到 Trae Solo：JSON 变回 `mcpServers` + `type: "http"`，写入位置提示变为 Trae IDE
- 三个 tab 都看到 `<YOUR_API_KEY>` 字面量
- 浏览器 Console 无 JS 报错

如果 server 已被其他方式启动，关掉再用上面命令重启，确保拿到最新代码。

- [ ] **Step 3: 关闭 server，提交**

按 Ctrl+C 关闭 uvicorn。

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: add MCP config modal JS logic for Claude Code/OpenCode/Trae"
```

---

### Task 3: 全量回归测试 + 最终端到端验证清单

**Files:** 无修改

- [ ] **Step 1: 跑全量 pytest 回归**

Run: `uv run pytest`

Expected: 全部 PASS（特别是 `tests/test_pages.py` 全部用例）

如果有失败，定位是否与本次改动相关——理论上 Task 1 的测试已覆盖 dashboard 改动，其他测试不应受影响。

- [ ] **Step 2: 启动 server 走完整手动验证清单**

```bash
uv run uvicorn hindsight_manager.main:app --reload --port 8001
```

在浏览器逐项核对：

1. 登录后到 `/dashboard`，顶部 `.usage-guide` 块：API 地址行还在、原 MCP 地址行消失、"获取 MCP 配置"按钮可见
2. 点按钮 → 弹窗打开，MCP 地址行正确显示实际地址
3. 默认 Claude Code tab 高亮，代码框 JSON 正确
4. 切到 OpenCode：JSON 切换为 `mcp`/`remote` 结构
5. 切到 Trae Solo：JSON 切回 `mcpServers`/`http` 结构
6. 每个 tab 下方的"写入位置"提示对应正确
7. 复制 MCP 地址按钮：剪贴板得到 MCP 地址
8. 复制 JSON 按钮：剪贴板得到当前 tab 的 JSON
9. 占位符 `<YOUR_API_KEY>` 在三个 tab 都保留为字面量
10. 弹窗底部提示行包含到 `/api-keys` 的链接
11. 点背景或"关闭"按钮 → 弹窗关闭
12. 关闭后再打开 → 状态重置回 Claude Code tab（因为 `showMcpConfigModal` 总是先 `switchMcpTab("claude")`）
13. 没有 tenant 的用户也能用此按钮（dashboard 本身就对这个用户渲染，弹窗与 tenant 无关）

- [ ] **Step 3: 关闭 server**

按 Ctrl+C 关闭 uvicorn。所有改动已在 Task 1、Task 2 提交，本任务无需额外 commit。

---

## Self-Review 结果

**Spec coverage（逐节核对）：**
- 节 1（用户流程与入口）：Task 1 删旧行 + 加按钮 + 加弹窗 ✓；Task 2 实现打开/关闭/切换 ✓
- 节 2（三框架模板）：Task 2 `MCP_TEMPLATES` 三个 key 与 spec 完全一致 ✓
- 节 3（前端实现）：dashboard.html 改动 ✓、app.js 4 函数 + 3 模板 ✓、不动后端 ✓、`window.MCP_URL` 注入 ✓
- 节 4（测试）：Task 1 扩展 pytest ✓；Task 3 全量回归 + 手动清单 13 项 ✓

**Placeholder scan：** 无 TBD/TODO/"实现细节后补"；所有代码块均为完整可粘贴代码。

**Type consistency：** Task 1 产出的 DOM id/class 与 Task 2 JS 中引用的 selector 完全匹配：`mcp-config-modal`、`mcp-config-code`、`mcp-config-location`、`.mcp-tab[data-framework]`、`window.MCP_URL`。函数名 `showMcpConfigModal` / `hideMcpConfigModal` / `switchMcpTab` 在两个任务间一致。
