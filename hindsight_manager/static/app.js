let _activeApiKeysTenantId = null;

async function enterConsole(tenantId, tenantSlug) {
  try {
    const resp = await fetch(`/auth/otp?tenant_id=${tenantId}`, {
      method: "POST",
      credentials: "include",
    });
    if (!resp.ok) {
      alert("获取授权失败");
      return;
    }
    const { otp, redirect_url } = await resp.json();
    const cpSsoUrl = redirect_url + "api/auth/sso";
    // Open POST-form redirect page — OTP goes via POST body, never in URL
    window.open(`/auth/otp/redirect?otp=${encodeURIComponent(otp)}&cp_url=${encodeURIComponent(cpSsoUrl)}`, "_blank");
  } catch (e) {
    alert("网络错误");
  }
}

async function createTenant(e) {
  e.preventDefault();
  const name = document.getElementById("tenant-name").value;
  try {
    const resp = await fetch("/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      window.location.reload();
    } else {
      const err = await resp.json();
      alert(err.detail || "创建失败");
    }
  } catch (e) {
    alert("网络错误");
  }
}

async function deleteTenant(tenantId, tenantName) {
  if (!confirm(`确定删除记忆库 "${tenantName}" 吗？此操作不可撤销。`)) return;
  try {
    const resp = await fetch(`/tenants/${tenantId}`, {
      method: "DELETE",
      credentials: "include",
    });
    if (resp.ok) {
      window.location.reload();
    } else {
      alert("删除失败");
    }
  } catch (e) {
    alert("网络错误");
  }
}

function showCreateModal() {
  document.getElementById("create-modal").classList.remove("hidden");
  document.getElementById("tenant-name").focus();
}

function hideCreateModal() {
  document.getElementById("create-modal").classList.add("hidden");
}

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
        <span class="api-key-item-name">${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}</span>
        <div class="api-key-item-detail">
          <code>${escapeHtml(k.key_prefix)}...</code>
          <span>创建于 ${formatDate(k.created_at)}</span>
          ${k.last_used_at ? `<span>最后使用 ${formatDate(k.last_used_at)}</span>` : '<span>未使用</span>'}
        </div>
      </div>
      ${!k.is_system ? `<div class="api-key-item-actions">
        <button class="btn btn-ghost btn-sm" onclick="copyKey('${escapeHtml(k.key_prefix)}...')">复制前缀</button>
        <button class="btn btn-danger btn-sm" onclick="revokeApiKey('${tenantId}', '${k.id}')">删除</button>
      </div>` : ''}
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
  const select = document.getElementById("mcp-framework-select");
  if (select && select.value !== framework) select.value = framework;
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
