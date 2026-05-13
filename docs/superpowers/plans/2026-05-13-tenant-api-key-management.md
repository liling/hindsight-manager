# 租户 API Key 管理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dashboard 租户卡片内实现 API Key 的创建、列表展示、复制和删除功能。

**Architecture:** 纯 JavaScript 调用现有 REST API，动态渲染展开区域。每个租户卡片下方有可折叠的 API Key 管理面板，同时只展开一个。创建通过模态框完成，创建成功后一次性展示完整 key。

**Tech Stack:** 原生 JavaScript + Jinja2 模板 + CSS（与现有代码风格一致）

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `hindsight_manager/templates/dashboard.html` | 租户卡片增加展开容器 + 创建 API Key 模态框 HTML |
| `hindsight_manager/static/app.js` | API Key 列表加载、创建、删除、复制的 JS 函数 |
| `hindsight_manager/static/style.css` | 展开面板、Key 列表项、创建结果展示样式 |

后端不改动。现有 API：
- `POST /tenants/{tenant_id}/api-keys` → `{id, name, key_prefix, created_at, last_used_at, key}`
- `GET /tenants/{tenant_id}/api-keys` → `[{id, name, key_prefix, created_at, last_used_at}]`
- `DELETE /tenants/{tenant_id}/api-keys/{key_id}` → `{ok: true}`

---

### Task 1: CSS 样式

**Files:**
- Modify: `hindsight_manager/static/style.css`

- [ ] **Step 1: 添加 API Key 管理面板样式**

在 `style.css` 文件末尾的 `/* ── Responsive ── */` 之前添加以下样式：

```css
/* ── API Keys Panel (Dashboard) ── */
.api-keys-panel {
    background: var(--bg);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius) var(--radius);
    padding: 18px 22px;
}
.api-keys-panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
}
.api-keys-panel-header h4 {
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
}
.api-key-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    margin-bottom: 8px;
}
.api-key-item:last-child {
    margin-bottom: 0;
}
.api-key-item-info {
    display: flex;
    flex-direction: column;
    gap: 3px;
}
.api-key-item-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
}
.api-key-item-detail {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
    color: var(--text-muted);
}
.api-key-item-detail code {
    background: var(--bg);
    padding: 1px 6px;
    border-radius: 4px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 12px;
    color: var(--text-secondary);
}
.api-key-item-actions {
    display: flex;
    align-items: center;
    gap: 6px;
}
.api-key-empty {
    text-align: center;
    padding: 24px;
    color: var(--text-muted);
    font-size: 13.5px;
}
.api-key-result {
    margin-top: 16px;
    padding: 14px;
    background: var(--success-bg);
    border: 1px solid var(--success-border);
    border-radius: var(--radius-sm);
}
.api-key-result-key {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
}
.api-key-result-key code {
    flex: 1;
    padding: 8px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 13px;
    word-break: break-all;
    color: var(--text);
}
.api-key-result-warning {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-top: 10px;
    font-size: 12.5px;
    color: #92400e;
    background: #fffbeb;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
}
```

- [ ] **Step 2: 添加面板展开时租户卡片的样式**

在同一位置追加：

```css
.tenant-card.has-panel {
    border-radius: var(--radius) var(--radius) 0 0;
    border-bottom-color: transparent;
}
```

- [ ] **Step 3: 添加响应式样式**

在 `@media (max-width: 768px)` 块内追加：

```css
    .api-key-item {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
    }
    .api-key-item-actions {
        align-self: flex-end;
    }
```

- [ ] **Step 4: 提交**

```bash
git add hindsight_manager/static/style.css
git commit -m "style: add API key management panel styles"
```

---

### Task 2: Dashboard HTML 模板

**Files:**
- Modify: `hindsight_manager/templates/dashboard.html`

- [ ] **Step 1: 修改租户卡片结构**

将现有的租户卡片循环（第 16-29 行）替换为以下结构。每张卡片后紧跟一个展开面板容器：

```html
    {% for t in tenants %}
    <div>
        <div class="tenant-card" id="tenant-card-{{ t.id }}">
            <div class="tenant-info">
                <h3>{{ t.name }}</h3>
                <span class="tenant-meta">{{ t.schema_name }} · {{ t.role }}</span>
            </div>
            <div class="tenant-actions">
                <button class="btn btn-primary btn-sm" onclick="enterConsole('{{ t.id }}', '{{ t.schema_name }}')">进入控制台</button>
                {% if t.role == 'owner' %}
                <button class="btn btn-secondary btn-sm" onclick="toggleApiKeys('{{ t.id }}')">API Keys</button>
                <button class="btn btn-danger btn-sm" onclick="deleteTenant('{{ t.id }}', '{{ t.name }}')">删除</button>
                {% endif %}
            </div>
        </div>
        <div id="api-keys-panel-{{ t.id }}" class="api-keys-panel" style="display:none"></div>
    </div>
    {% endfor %}
```

- [ ] **Step 2: 替换页面底部的 showApiKeys 脚本**

将现有的 `<script>` 块（第 51-55 行）替换为空占位（JS 函数将在 app.js 中添加）：

```html
<script src="/static/app.js"></script>
```

- [ ] **Step 3: 在创建租户模态框之后添加创建 API Key 模态框**

在 `</div>` (create-modal 结束) 之后、`<script src>` 之前，添加：

```html

<div id="apikey-modal" class="modal hidden">
    <div class="modal-backdrop" onclick="hideApiKeyModal()"></div>
    <div class="modal-content">
        <h3>创建 API Key</h3>
        <div id="apikey-modal-form">
            <form id="apikey-form" onsubmit="createApiKey(event)">
                <div class="form-group">
                    <label for="apikey-name">名称</label>
                    <input type="text" id="apikey-name" name="name" required placeholder="输入 API Key 名称">
                    <input type="hidden" id="apikey-tenant-id">
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="hideApiKeyModal()">取消</button>
                    <button type="submit" class="btn btn-primary">创建</button>
                </div>
            </form>
        </div>
        <div id="apikey-modal-result" class="api-key-result" style="display:none">
            <p style="font-weight:600;color:var(--success-text)">API Key 创建成功</p>
            <p style="font-size:13px;margin-top:6px;color:var(--text-secondary)">请立即复制，关闭后将无法再次查看完整 Key。</p>
            <div class="api-key-result-key">
                <code id="apikey-result-value"></code>
                <button type="button" class="btn btn-secondary btn-sm" onclick="copyKey(document.getElementById('apikey-result-value').textContent)">复制</button>
            </div>
            <div class="api-key-result-warning">
                <span>&#9888;</span>
                <span>关闭此对话框后，完整 Key 将不再显示。请确保已妥善保存。</span>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-primary" onclick="hideApiKeyModal()">我已保存</button>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 4: 提交**

```bash
git add hindsight_manager/templates/dashboard.html
git commit -m "feat: add API key panel and create modal to dashboard template"
```

---

### Task 3: JavaScript 交互逻辑

**Files:**
- Modify: `hindsight_manager/static/app.js`

- [ ] **Step 1: 添加全局状态变量**

在 `app.js` 文件顶部（第 1 行之前）添加：

```javascript
let _activeApiKeysTenantId = null;
let _activeApiKeysTenantName = '';

```

- [ ] **Step 2: 添加 toggleApiKeys 函数**

在文件末尾追加：

```javascript

function toggleApiKeys(tenantId) {
  const panel = document.getElementById(`api-keys-panel-${tenantId}`);
  const card = document.getElementById(`tenant-card-${tenantId}`);
  if (!panel) return;

  if (_activeApiKeysTenantId === tenantId) {
    panel.style.display = 'none';
    card.classList.remove('has-panel');
    _activeApiKeysTenantId = null;
    return;
  }

  if (_activeApiKeysTenantId) {
    const prevPanel = document.getElementById(`api-keys-panel-${_activeApiKeysTenantId}`);
    const prevCard = document.getElementById(`tenant-card-${_activeApiKeysTenantId}`);
    if (prevPanel) prevPanel.style.display = 'none';
    if (prevCard) prevCard.classList.remove('has-panel');
  }

  _activeApiKeysTenantId = tenantId;
  card.classList.add('has-panel');
  panel.style.display = 'block';
  loadApiKeys(tenantId);
}
```

- [ ] **Step 3: 添加 loadApiKeys 函数**

追加：

```javascript

async function loadApiKeys(tenantId) {
  const panel = document.getElementById(`api-keys-panel-${tenantId}`);
  panel.innerHTML = '<div class="api-key-empty">加载中...</div>';

  try {
    const resp = await fetch(`/tenants/${tenantId}/api-keys`, { credentials: 'include' });
    if (!resp.ok) {
      panel.innerHTML = '<div class="api-key-empty">加载失败，请重试</div>';
      return;
    }
    const keys = await resp.json();
    renderApiKeysList(panel, tenantId, keys);
  } catch (e) {
    panel.innerHTML = '<div class="api-key-empty">网络错误</div>';
  }
}

function renderApiKeysList(panel, tenantId, keys) {
  let html = `<div class="api-keys-panel-header">
    <h4>API Keys</h4>
    <button class="btn btn-primary btn-sm" onclick="showApiKeyModal('${tenantId}')">+ 创建</button>
  </div>`;

  if (keys.length === 0) {
    html += '<div class="api-key-empty">还没有 API Key，点击上方按钮创建一个。</div>';
    panel.innerHTML = html;
    return;
  }

  html += keys.map(k => `
    <div class="api-key-item" id="api-key-${k.id}">
      <div class="api-key-item-info">
        <span class="api-key-item-name">${escapeHtml(k.name)}</span>
        <div class="api-key-item-detail">
          <code>${escapeHtml(k.key_prefix)}...</code>
          <span>创建于 ${formatDate(k.created_at)}</span>
          ${k.last_used_at ? `<span>最后使用 ${formatDate(k.last_used_at)}</span>` : '<span>未使用</span>'}
        </div>
      </div>
      <div class="api-key-item-actions">
        <button class="btn btn-ghost btn-sm" onclick="copyKey('${escapeHtml(k.key_prefix)}...')">复制前缀</button>
        <button class="btn btn-danger btn-sm" onclick="revokeApiKey('${tenantId}', '${k.id}')">删除</button>
      </div>
    </div>
  `).join('');

  panel.innerHTML = html;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
```

- [ ] **Step 4: 添加创建 API Key 模态框函数**

追加：

```javascript

function showApiKeyModal(tenantId) {
  document.getElementById('apikey-tenant-id').value = tenantId;
  document.getElementById('apikey-name').value = '';
  document.getElementById('apikey-modal-form').style.display = 'block';
  document.getElementById('apikey-modal-result').style.display = 'none';
  document.getElementById('apikey-modal').classList.remove('hidden');
  document.getElementById('apikey-name').focus();
}

function hideApiKeyModal() {
  document.getElementById('apikey-modal').classList.add('hidden');
  if (_activeApiKeysTenantId) {
    loadApiKeys(_activeApiKeysTenantId);
  }
}

async function createApiKey(e) {
  e.preventDefault();
  const tenantId = document.getElementById('apikey-tenant-id').value;
  const name = document.getElementById('apikey-name').value;

  try {
    const resp = await fetch(`/tenants/${tenantId}/api-keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert(err.detail || '创建失败');
      return;
    }
    const data = await resp.json();
    document.getElementById('apikey-modal-form').style.display = 'none';
    document.getElementById('apikey-result-value').textContent = data.key;
    document.getElementById('apikey-modal-result').style.display = 'block';
  } catch (e) {
    alert('网络错误');
  }
}
```

- [ ] **Step 5: 添加删除和复制函数**

追加：

```javascript

async function revokeApiKey(tenantId, keyId) {
  if (!confirm('确定删除此 API Key 吗？删除后使用该 Key 的应用将无法访问。')) return;

  try {
    const resp = await fetch(`/tenants/${tenantId}/api-keys/${keyId}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!resp.ok) {
      alert('删除失败');
      return;
    }
    const el = document.getElementById(`api-key-${keyId}`);
    if (el) {
      el.style.opacity = '0';
      el.style.transition = 'opacity 200ms';
      setTimeout(() => el.remove(), 200);
      const panel = document.getElementById(`api-keys-panel-${tenantId}`);
      if (panel && panel.querySelectorAll('.api-key-item').length <= 1) {
        setTimeout(() => loadApiKeys(tenantId), 250);
      }
    }
  } catch (e) {
    alert('网络错误');
  }
}

function copyKey(text) {
  navigator.clipboard.writeText(text).then(() => {
    const toast = document.createElement('div');
    toast.textContent = '已复制到剪贴板';
    toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:8px 18px;background:var(--text);color:#fff;border-radius:8px;font-size:13px;font-weight:500;z-index:100;';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
  });
}
```

- [ ] **Step 6: 提交**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: add API key CRUD JavaScript functions for dashboard"
```

---

### Task 4: 手动验证

- [ ] **Step 1: 启动开发服务器**

```bash
cd /Users/liling/src/lab/hindsight-manager && uvicorn hindsight_manager.main:app --reload --port 8001
```

- [ ] **Step 2: 浏览器验证清单**

打开 `http://localhost:8001/dashboard`，逐项验证：

1. 租户卡片显示"API Keys"按钮
2. 点击"API Keys"按钮，卡片下方展开面板，显示 API Key 列表
3. 再点击同一按钮，面板折叠
4. 展开租户 A 的面板，再展开租户 B 的面板 → A 自动折叠
5. 空状态显示"还没有 API Key"引导文案
6. 点击"+ 创建"按钮弹出模态框
7. 输入名称，点击创建 → 模态框切换为结果展示，显示完整 key
8. 点击"复制"按钮 → 剪贴板有内容，底部显示提示
9. 点击"我已保存"关闭模态框 → 列表刷新，新 key 出现
10. 点击"复制前缀"按钮 → 剪贴板有内容
11. 点击"删除"按钮 → 确认对话框 → 确认后 key 从列表消失
12. 响应式：缩小窗口到手机宽度，面板和列表项正确排列

- [ ] **Step 3: 确认所有功能正常后，合并提交**

如果验证过程中发现 bug，修复后单独提交。全部通过后最终提交：

```bash
git add -A
git commit -m "feat: complete tenant API key management in dashboard"
```
