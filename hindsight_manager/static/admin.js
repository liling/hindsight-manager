// ─── 通用工具 ───

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;").replace(/"/g, "&quot;");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(isoStr) {
  if (!isoStr) return "-";
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, { credentials: "include", ...options });
  if (resp.status === 403) {
    alert("无权限访问");
    window.location.href = "/dashboard";
    return null;
  }
  return resp;
}

function renderPagination(containerId, total, page, pageSize, onPageChange) {
  const container = document.getElementById(containerId);
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }
  let html = '<div class="pagination-info">共 ' + total + ' 条</div><div class="pagination-btns">';
  if (page > 1) html += '<button class="btn btn-ghost btn-sm" onclick="' + onPageChange + '(' + (page - 1) + ')">上一页</button>';
  html += '<span class="pagination-current">' + page + ' / ' + totalPages + '</span>';
  if (page < totalPages) html += '<button class="btn btn-ghost btn-sm" onclick="' + onPageChange + '(' + (page + 1) + ')">下一页</button>';
  html += '</div>';
  container.innerHTML = html;
}

// ─── 用户管理 ───

let _userPage = 1;
let _userSearch = "";

async function loadUsers(page = 1) {
  _userPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  if (_userSearch) params.set("search", _userSearch);

  const resp = await apiFetch(`/admin/api/users?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("users-tbody");
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(u => `
      <tr>
        <td>${escapeHtml(u.username)}</td>
        <td>${escapeHtml(u.email || "-")}</td>
        <td><span class="badge ${u.role === 'admin' ? 'badge-system' : 'badge-default'}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
        <td><span class="badge ${u.is_active ? 'badge-success' : 'badge-danger'}">${u.is_active ? '启用' : '禁用'}</span></td>
        <td>${formatDate(u.created_at)}</td>
        <td>${formatDate(u.last_login_at)}</td>
        <td class="action-cell">
          <button class="btn btn-ghost btn-sm" onclick="showEditUserModal('${u.id}','${escapeHtml(u.display_name)}','${escapeHtml(u.email || '')}','${u.role}')">编辑</button>
          <button class="btn btn-ghost btn-sm" onclick="showResetPasswordModal('${u.id}')">重置密码</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleUserActive('${u.id}', ${u.is_active})">${u.is_active ? '禁用' : '启用'}</button>
        </td>
      </tr>
    `).join("");
  }

  renderPagination("users-pagination", data.total, data.page, data.page_size, "loadUsers");
}

function searchUsers() {
  _userSearch = document.getElementById("user-search").value.trim();
  loadUsers(1);
}

function showCreateUserModal() {
  document.getElementById("create-user-form").reset();
  document.getElementById("create-user-modal").classList.remove("hidden");
}

function hideCreateUserModal() {
  document.getElementById("create-user-modal").classList.add("hidden");
}

async function createUser(e) {
  e.preventDefault();
  const resp = await apiFetch("/admin/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.getElementById("cu-username").value,
      password: document.getElementById("cu-password").value,
      display_name: document.getElementById("cu-display-name").value,
      email: document.getElementById("cu-email").value || null,
      role: document.getElementById("cu-role").value,
    }),
  });
  if (!resp) return;
  if (resp.ok) {
    hideCreateUserModal();
    loadUsers();
  } else {
    const err = await resp.json();
    alert(err.detail || "创建失败");
  }
}

function showEditUserModal(id, displayName, email, role) {
  document.getElementById("eu-id").value = id;
  document.getElementById("eu-display-name").value = displayName;
  document.getElementById("eu-email").value = email;
  document.getElementById("eu-role").value = role;
  document.getElementById("edit-user-modal").classList.remove("hidden");
}

function hideEditUserModal() {
  document.getElementById("edit-user-modal").classList.add("hidden");
}

async function updateUser(e) {
  e.preventDefault();
  const id = document.getElementById("eu-id").value;
  const resp = await apiFetch(`/admin/api/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      display_name: document.getElementById("eu-display-name").value,
      email: document.getElementById("eu-email").value || null,
      role: document.getElementById("eu-role").value,
    }),
  });
  if (!resp) return;
  if (resp.ok) {
    hideEditUserModal();
    loadUsers(_userPage);
  } else {
    const err = await resp.json();
    alert(err.detail || "更新失败");
  }
}

function showResetPasswordModal(id) {
  document.getElementById("rp-id").value = id;
  document.getElementById("rp-password").value = "";
  document.getElementById("reset-password-modal").classList.remove("hidden");
}

function hideResetPasswordModal() {
  document.getElementById("reset-password-modal").classList.add("hidden");
}

async function resetPassword(e) {
  e.preventDefault();
  const id = document.getElementById("rp-id").value;
  const resp = await apiFetch(`/admin/api/users/${id}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_password: document.getElementById("rp-password").value }),
  });
  if (!resp) return;
  if (resp.ok) {
    alert("密码重置成功");
    hideResetPasswordModal();
  } else {
    const err = await resp.json();
    alert(err.detail || "重置失败");
  }
}

async function toggleUserActive(id, isActive) {
  const action = isActive ? "禁用" : "启用";
  if (!confirm(`确定${action}该用户吗？`)) return;
  const resp = await apiFetch(`/admin/api/users/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadUsers(_userPage);
  } else {
    const err = await resp.json();
    alert(err.detail || "操作失败");
  }
}

// ─── 租户管理 ───

let _tenantPage = 1;
let _tenantSearch = "";

async function loadTenants(page = 1) {
  _tenantPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  if (_tenantSearch) params.set("search", _tenantSearch);

  const resp = await apiFetch(`/admin/api/tenants?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("tenants-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(t => `
      <tr>
        <td>${escapeHtml(t.name)}</td>
        <td><code>${escapeHtml(t.schema_name)}</code></td>
        <td>${escapeHtml(t.owner || "-")}</td>
        <td><span class="badge ${t.status === 'active' ? 'badge-success' : 'badge-danger'}">${t.status === 'deleting' ? '待清空' : escapeHtml(t.status)}</span></td>
        <td>${t.member_count}</td>
        <td>${t.api_key_count}</td>
        <td>${formatDate(t.created_at)}</td>
        <td class="action-cell">
          ${t.status === 'active' ? `<button class="btn btn-danger btn-sm" onclick="deleteTenantAdmin('${t.id}','${escapeAttr(t.name)}')">删除</button>` : ''}
          ${t.status === 'deleting' ? `<button class="btn btn-danger btn-sm" onclick="purgeTenantAdmin('${t.id}','${escapeAttr(t.name)}','${escapeAttr(t.schema_name)}')">清空</button>` : ''}
        </td>
      </tr>
    `).join("");
  }

  renderPagination("tenants-pagination", data.total, data.page, data.page_size, "loadTenants");
}

function searchTenants() {
  _tenantSearch = document.getElementById("tenant-search").value.trim();
  loadTenants(1);
}

async function deleteTenantAdmin(id, name) {
  if (!confirm(`确定删除租户 "${name}" 吗？此操作不可撤销。`)) return;
  const resp = await apiFetch(`/admin/api/tenants/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadTenants(_tenantPage);
  } else {
    alert("删除失败");
  }
}

function hidePurgeModal() {
  document.getElementById("purge-modal").classList.add("hidden");
}

function showPurgeConfirmDialog(name, schemaName) {
  return new Promise(resolve => {
    const modal = document.getElementById("purge-modal");
    const nameEl = document.getElementById("purge-confirm-name");
    const schemaEl = document.getElementById("purge-confirm-schema");
    const input = document.getElementById("purge-confirm-input");
    const confirmBtn = document.getElementById("purge-confirm");
    const cancelBtn = document.getElementById("purge-cancel-btn");
    const backdrop = document.getElementById("purge-modal-backdrop");

    nameEl.textContent = name;
    schemaEl.textContent = schemaName;
    input.value = "";
    confirmBtn.disabled = true;
    modal.classList.remove("hidden");

    function cleanup() {
      modal.removeEventListener("keydown", onKeydown);
      confirmBtn.removeEventListener("click", onConfirm);
      cancelBtn.removeEventListener("click", onCancel);
      backdrop.removeEventListener("click", onCancel);
    }
    function onKeydown(e) {
      if (e.key === "Escape") { cleanup(); hidePurgeModal(); resolve(false); }
    }
    function onConfirm() { cleanup(); hidePurgeModal(); resolve(true); }
    function onCancel() { cleanup(); hidePurgeModal(); resolve(false); }

    input.oninput = () => { confirmBtn.disabled = input.value.trim() !== name; };
    modal.addEventListener("keydown", onKeydown);
    confirmBtn.addEventListener("click", onConfirm);
    cancelBtn.addEventListener("click", onCancel);
    backdrop.addEventListener("click", onCancel);
    input.focus();
  });
}

async function purgeTenantAdmin(id, name, schemaName) {
  const confirmed = await showPurgeConfirmDialog(name, schemaName);
  if (!confirmed) return;

  const resp = await apiFetch(`/admin/api/tenants/${id}/purge`, { method: "POST" });
  if (!resp) return;
  if (resp.ok) {
    loadTenants(_tenantPage);
  } else if (resp.status === 409) {
    const err = await resp.json();
    alert(err.detail || "清空失败：租户数据尚未完全迁移，请稍后重试");
  } else {
    const err = await resp.json();
    alert(err.detail || "清空失败");
  }
}

// ─── API Key 管理 ───

let _apiKeyPage = 1;

async function loadApiKeys(page = 1) {
  _apiKeyPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  const tenantFilter = document.getElementById("ak-tenant-filter");
  if (tenantFilter && tenantFilter.value) params.set("tenant_id", tenantFilter.value);

  const resp = await apiFetch(`/admin/api/api-keys?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("apikeys-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(k => `
      <tr>
        <td>${escapeHtml(k.tenant_name)}</td>
        <td>${escapeHtml(k.name)}${k.is_system ? ' <span class="badge badge-system">系统</span>' : ''}</td>
        <td><code>${escapeHtml(k.key_prefix)}...</code></td>
        <td>${formatDate(k.created_at)}</td>
        <td>${formatDate(k.last_used_at)}</td>
        <td class="action-cell">
          <button class="btn btn-danger btn-sm" onclick="revokeApiKeyAdmin('${k.id}')">撤销</button>
        </td>
      </tr>
    `).join("");
  }

  renderPagination("apikeys-pagination", data.total, data.page, data.page_size, "loadApiKeys");
}

async function revokeApiKeyAdmin(id) {
  if (!confirm("确定撤销此 API Key 吗？使用该 Key 的应用将无法访问。")) return;
  const resp = await apiFetch(`/admin/api/api-keys/${id}`, { method: "DELETE" });
  if (!resp) return;
  if (resp.ok) {
    loadApiKeys(_apiKeyPage);
  } else {
    alert("撤销失败");
  }
}

// ─── 审计日志 ───

let _auditPage = 1;

async function loadAuditLogs(page = 1) {
  _auditPage = page;
  const params = new URLSearchParams({ page, page_size: 20 });
  const actionFilter = document.getElementById("al-action-filter");
  if (actionFilter && actionFilter.value) params.set("action", actionFilter.value);

  const resp = await apiFetch(`/admin/api/audit-logs?${params}`);
  if (!resp) return;
  const data = await resp.json();

  const tbody = document.getElementById("audit-tbody");
  if (!tbody) return;
  if (data.items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map(l => `
      <tr>
        <td>${formatDate(l.created_at)}</td>
        <td>${escapeHtml(l.username || "-")}</td>
        <td><code>${escapeHtml(l.action)}</code></td>
        <td>${escapeHtml(l.resource_type)}</td>
        <td><code>${escapeHtml(l.resource_id).substring(0, 8)}...</code></td>
        <td>${escapeHtml(l.ip_address || "-")}</td>
        <td>${l.detail ? `<button class="btn btn-ghost btn-sm" onclick="alert(JSON.stringify(${JSON.stringify(l.detail)}, null, 2))">查看</button>` : "-"}</td>
      </tr>
    `).join("");
  }

  renderPagination("audit-pagination", data.total, data.page, data.page_size, "loadAuditLogs");
}
