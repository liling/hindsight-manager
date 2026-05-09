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
    const { redirect_url } = await resp.json();
    window.location.href = redirect_url;
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
