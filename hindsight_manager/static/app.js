let _activePanel = null; // { tenantId: string, type: 'api-keys' | 'members' }

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

function showRenameModal(tenantId, currentName) {
  document.getElementById("rename-tenant-id").value = tenantId;
  const input = document.getElementById("rename-name");
  input.value = currentName;
  document.getElementById("rename-modal").classList.remove("hidden");
  input.focus();
  input.select();
}

function hideRenameModal() {
  document.getElementById("rename-modal").classList.add("hidden");
}

function showRenameApikeyModal(tenantId, keyId, currentName) {
  document.getElementById("rename-apikey-id").value = keyId;
  document.getElementById("rename-apikey-tenant").value = tenantId;
  const input = document.getElementById("rename-apikey-name");
  input.value = currentName;
  document.getElementById("rename-apikey-modal").classList.remove("hidden");
  input.focus();
  input.select();
}

function hideRenameApikeyModal() {
  document.getElementById("rename-apikey-modal").classList.add("hidden");
}

async function renameApiKey(e) {
  e.preventDefault();
  const keyId = document.getElementById("rename-apikey-id").value;
  const tenantId = document.getElementById("rename-apikey-tenant").value;
  const name = document.getElementById("rename-apikey-name").value;
  try {
    const resp = await fetch(`/tenants/${tenantId}/api-keys/${keyId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      hideRenameApikeyModal();
      loadApiKeys(tenantId);
    } else {
      const data = await resp.json().catch(() => ({}));
      alert(data.detail || "重命名失败");
    }
  } catch (err) {
    alert("网络错误，重命名失败");
  }
}

async function renameTenant(e) {
  e.preventDefault();
  const tenantId = document.getElementById("rename-tenant-id").value;
  const name = document.getElementById("rename-name").value;
  try {
    const resp = await fetch(`/tenants/${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      window.location.reload();
    } else {
      const err = await resp.json();
      alert(err.detail || "重命名失败");
    }
  } catch (e) {
    alert("网络错误");
  }
}

function _closePanel() {
  if (!_activePanel) return;
  const prevPanel = document.getElementById(
    _activePanel.type === 'api-keys'
      ? `api-keys-panel-${_activePanel.tenantId}`
      : `members-panel-${_activePanel.tenantId}`
  );
  const prevCard = document.getElementById(`tenant-card-${_activePanel.tenantId}`);
  if (prevPanel) prevPanel.style.display = 'none';
  if (prevCard) prevCard.classList.remove('has-panel');
  _activePanel = null;
}

function toggleApiKeys(tenantId) {
  const panel = document.getElementById(`api-keys-panel-${tenantId}`);
  const card = document.getElementById(`tenant-card-${tenantId}`);
  if (!panel) return;

  if (_activePanel && _activePanel.tenantId === tenantId && _activePanel.type === 'api-keys') {
    _closePanel();
    return;
  }

  _closePanel();
  _activePanel = { tenantId, type: 'api-keys' };
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
        <span class="api-key-item-name">${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}${!k.is_system ? ` <button type="button" class="api-key-edit-btn" title="重命名" aria-label="重命名" onclick='showRenameApikeyModal(${attrJson(tenantId)}, ${attrJson(k.id)}, ${attrJson(k.name)})'><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg></button>` : ''}</span>
        <div class="api-key-item-detail">
          <code>${escapeHtml(k.key_prefix)}...</code>
          <span>创建于 ${formatDate(k.created_at)}</span>
          ${k.last_used_at ? `<span>最后使用 ${formatDate(k.last_used_at)}</span>` : '<span>未使用</span>'}
        </div>
      </div>
      ${!k.is_system ? `<div class="api-key-item-actions">
        <button class="btn btn-ghost btn-sm" onclick='copyKey(${attrJson(k.key_prefix + "...")})'>复制前缀</button>
        <button class="btn btn-danger btn-sm" onclick='revokeApiKey(${attrJson(tenantId)}, ${attrJson(k.id)})'>删除</button>
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

function attrJson(value) {
  return JSON.stringify(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/'/g, '&#39;')
    .replace(/"/g, '&quot;');
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
  if (_activePanel && _activePanel.type === 'api-keys') {
    loadApiKeys(_activePanel.tenantId);
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

// ============ 成员管理面板 ============

function toggleMembers(tenantId, role, currentUserId) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  const card = document.getElementById(`tenant-card-${tenantId}`);
  if (!panel) return;

  if (_activePanel && _activePanel.tenantId === tenantId && _activePanel.type === 'members') {
    _closePanel();
    return;
  }

  _closePanel();
  _activePanel = { tenantId, type: 'members' };
  card.classList.add('has-panel');
  panel.style.display = 'block';
  loadMembers(tenantId, role, currentUserId);
}

async function loadMembers(tenantId, role, currentUserId) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  panel.innerHTML = '<div class="member-empty">加载中...</div>';

  const showError = (msg) => {
    panel.innerHTML = `<div class="member-empty">${msg}，<a href="#" class="member-retry">重试</a></div>`;
    panel.querySelector('.member-retry').addEventListener('click', (e) => {
      e.preventDefault();
      loadMembers(tenantId, role, currentUserId);
    });
  };

  try {
    const resp = await fetch(`/tenants/${tenantId}/members`, { credentials: 'include' });
    if (!resp.ok) {
      showError('加载失败');
      return;
    }
    const members = await resp.json();
    renderMembersPanel(panel, tenantId, members, role, currentUserId);
  } catch (e) {
    showError('网络错误');
  }
}

function renderMembersPanel(panel, tenantId, members, role, currentUserId) {
  // 缓存上下文到 dataset，供 changeMemberRole / removeMember 在事件回调里取回
  panel.dataset.currentRole = role;
  panel.dataset.currentUserId = currentUserId;
  panel.dataset.tenantId = tenantId;

  const isOwner = role === 'owner';
  const ownerCount = members.filter(m => m.role === 'owner').length;

  let html = `<div class="members-panel-header"><h4>成员</h4>${isOwner ? `<button class="btn btn-primary btn-sm" onclick="showMemberAddModal('${tenantId}','${role}','${currentUserId}')">+ 添加</button>` : ''}</div>`;

  if (members.length === 0) {
    html += '<div class="member-empty">暂无成员</div>';
    panel.innerHTML = html;
    return;
  }

  html += members.map(m => {
    const isSelf = m.user_id === currentUserId;
    const selfLastOwner = isSelf && m.role === 'owner' && ownerCount <= 1;
    const badge = m.role === 'owner'
      ? '<span class="role-badge role-owner">owner</span>'
      : '<span class="role-badge">member</span>';

    let actions = '';
    if (isOwner) {
      // 最后一个 owner 的下拉整体 disabled，防止降级导致无人管理
      const selectDisabled = selfLastOwner ? 'disabled' : '';
      actions = `<div class="member-actions">
        <select onchange="changeMemberRole('${tenantId}','${m.user_id}',this.value)" ${selectDisabled}>
          <option value="member" ${m.role === 'member' ? 'selected' : ''}>member</option>
          <option value="owner" ${m.role === 'owner' ? 'selected' : ''}>owner</option>
        </select>
        ${selfLastOwner ? '<span class="member-hint">至少保留一位 owner</span>' : ''}
        ${!isSelf ? `<button class="btn btn-danger btn-sm" onclick="removeMember('${tenantId}','${m.user_id}')">移除</button>` : ''}
      </div>`;
    }

    return `<div class="member-row" id="member-${m.user_id}" data-username="${escapeHtml(m.username)}">
      <div class="member-info">
        <span>${escapeHtml(m.username)}${isSelf ? '（你）' : ''}</span>
        ${badge}
      </div>
      ${actions}
    </div>`;
  }).join('');

  panel.innerHTML = html;
}

// ============ 成员添加弹窗 ============

function showMemberAddModal(tenantId, role, currentUserId) {
  const modal = document.getElementById('member-add-modal');
  modal.dataset.tenantId = tenantId;
  modal.dataset.role = role;
  modal.dataset.currentUserId = currentUserId;
  modal.dataset.lookupUserId = '';

  document.getElementById('member-username-input').value = '';
  document.getElementById('member-role-select').value = 'member';
  _resetMemberPreview();
  modal.classList.remove('hidden');
  document.getElementById('member-username-input').focus();
}

function hideMemberAddModal() {
  document.getElementById('member-add-modal').classList.add('hidden');
  if (_activePanel && _activePanel.type === 'members') {
    const panel = document.getElementById(`members-panel-${_activePanel.tenantId}`);
    if (panel) {
      loadMembers(_activePanel.tenantId, panel.dataset.currentRole, panel.dataset.currentUserId);
    }
  }
}

function _resetMemberPreview() {
  const preview = document.getElementById('member-preview');
  preview.style.display = 'none';
  preview.innerHTML = '';
  preview.className = 'member-preview';
  document.getElementById('member-add-submit').disabled = true;
}

function onMemberUsernameInput() {
  // 用户名改动后，旧的 lookup 结果失效，清掉 preview、禁用提交
  _resetMemberPreview();
}

async function lookupMember() {
  const modal = document.getElementById('member-add-modal');
  const tenantId = modal.dataset.tenantId;
  const username = document.getElementById('member-username-input').value.trim();
  if (!username) return;

  const preview = document.getElementById('member-preview');
  preview.style.display = 'block';
  preview.className = 'member-preview';
  preview.innerHTML = '<div class="member-preview-status-row"><span class="member-preview-status status-muted">查找中...</span></div>';
  document.getElementById('member-add-submit').disabled = true;
  modal.dataset.lookupUserId = '';

  try {
    const resp = await fetch(
      `/tenants/${tenantId}/members/lookup?username=${encodeURIComponent(username)}`,
      { credentials: 'include' }
    );
    if (resp.status === 404) {
      preview.className = 'member-preview is-error';
      preview.innerHTML = '<div class="member-preview-status-row"><span class="member-preview-status status-danger">用户不存在</span></div>';
      return;
    }
    if (!resp.ok) {
      preview.className = 'member-preview is-error';
      preview.innerHTML = '<div class="member-preview-status-row"><span class="member-preview-status status-danger">查找失败</span></div>';
      return;
    }
    const data = await resp.json();
    modal.dataset.lookupUserId = data.user_id;
    const identity = `<div class="member-preview-name">${escapeHtml(data.display_name)} <span class="member-preview-username">@${escapeHtml(data.username)}</span></div>`
      + (data.email ? `<div class="member-preview-email">${escapeHtml(data.email)}</div>` : '');
    if (data.is_already_member) {
      preview.className = 'member-preview is-conflict';
      preview.innerHTML = identity + '<div class="member-preview-status-row"><span class="member-preview-status status-warning">已是成员</span></div>';
      return;
    }
    preview.className = 'member-preview';
    preview.innerHTML = identity + '<div class="member-preview-status-row"><span class="member-preview-status status-success">可添加</span></div>';
    document.getElementById('member-add-submit').disabled = false;
  } catch (e) {
    preview.className = 'member-preview is-error';
    preview.innerHTML = '<div class="member-preview-status-row"><span class="member-preview-status status-danger">网络错误</span></div>';
  }
}

async function confirmAddMember(event) {
  event.preventDefault();
  const modal = document.getElementById('member-add-modal');
  const tenantId = modal.dataset.tenantId;
  const username = document.getElementById('member-username-input').value.trim();
  const role = document.getElementById('member-role-select').value;
  const preview = document.getElementById('member-preview');
  if (!username) return;

  try {
    const resp = await fetch(`/tenants/${tenantId}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, role }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const detail = data.detail || '添加失败';
      const msg = detail === 'User not found' ? '找不到该用户'
        : detail === 'User is already a member' ? '该用户已是成员'
        : detail === 'Owner access required' ? '无权限'
        : detail;
      preview.className = 'member-preview is-error';
      preview.innerHTML = `<div class="member-preview-status-row"><span class="member-preview-status status-danger">${escapeHtml(msg)}</span></div>`;
      return;
    }
    hideMemberAddModal();
  } catch (e) {
    preview.className = 'member-preview is-error';
    preview.innerHTML = '<div class="member-preview-status-row"><span class="member-preview-status status-danger">网络错误</span></div>';
  }
}

async function changeMemberRole(tenantId, userId, newRole) {
  const panel = document.getElementById(`members-panel-${tenantId}`);
  if (!panel) return;
  const currentUserId = panel.dataset.currentUserId;
  const role = panel.dataset.currentRole;
  const isSelfDowngrade = userId === currentUserId && newRole === 'member';

  if (isSelfDowngrade) {
    if (!confirm('你将失去管理权限，确定？')) {
      // 用户取消：重渲染面板让下拉还原到真实角色
      await loadMembers(tenantId, role, currentUserId);
      return;
    }
  }

  try {
    const resp = await fetch(`/tenants/${tenantId}/members/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ role: newRole }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.detail || '修改失败';
      alert(msg === 'Owner access required' ? '无权限' : msg);
      // 失败时下拉视觉会停在错误选项上，重渲染面板还原
      await loadMembers(tenantId, role, currentUserId);
      return;
    }
    if (isSelfDowngrade) {
      // 自降级后当前面板 role 已过期，按 spec 整页 reload
      window.location.reload();
      return;
    }
    await loadMembers(tenantId, role, currentUserId);
  } catch (e) {
    alert('网络错误');
  }
}

async function removeMember(tenantId, userId) {
  const row = document.getElementById(`member-${userId}`);
  const username = row ? row.dataset.username : userId;
  if (!confirm(`确定移除用户 ${username} 吗？`)) return;

  try {
    const resp = await fetch(`/tenants/${tenantId}/members/${userId}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.detail || '移除失败';
      alert(msg === 'Owner access required' ? '无权限' : msg);
      return;
    }
    const panel = document.getElementById(`members-panel-${tenantId}`);
    const role = panel.dataset.currentRole;
    const currentUserId = panel.dataset.currentUserId;
    await loadMembers(tenantId, role, currentUserId);
  } catch (e) {
    alert('网络错误');
  }
}
