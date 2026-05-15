let _taskCurrentPage = 1;

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

async function loadTaskStats() {
  try {
    const resp = await fetch('/admin/api/task-stats', { credentials: 'include' });
    if (!resp.ok) return;
    const data = await resp.json();

    const g = data.global;
    document.getElementById('stat-pending').textContent = g.pending;
    document.getElementById('stat-processing').textContent = g.processing;
    document.getElementById('stat-completed').textContent = g.completed;
    document.getElementById('stat-failed').textContent = g.failed;
    document.getElementById('stat-cancelled').textContent = g.cancelled;

    const tbody = document.querySelector('#task-tenant-table tbody');
    tbody.innerHTML = data.by_tenant.map(t => `
      <tr onclick="filterByTenant('${t.tenant_id}','${escapeHtml(t.tenant_name)}')" style="cursor:pointer">
        <td>${escapeHtml(t.tenant_name)}</td>
        <td>${t.stats.pending}</td>
        <td>${t.stats.processing}</td>
        <td>${t.stats.completed}</td>
        <td>${t.stats.failed}</td>
        <td>${t.stats.cancelled}</td>
      </tr>
    `).join('');

    const select = document.getElementById('filter-tenant');
    const currentVal = select.value;
    select.innerHTML = '<option value="">全部租户</option>' + data.by_tenant.map(t =>
      `<option value="${t.tenant_id}">${escapeHtml(t.tenant_name)}</option>`
    ).join('');
    select.value = currentVal;
  } catch (e) {
    console.error('Failed to load task stats:', e);
  }
}

function filterByTenant(tenantId, tenantName) {
  document.getElementById('filter-tenant').value = tenantId;
  _taskCurrentPage = 1;
  loadTaskDetails();
}

async function loadTaskDetails() {
  const tenantId = document.getElementById('filter-tenant').value;
  const status = document.getElementById('filter-status').value;
  const opType = document.getElementById('filter-type').value;

  const params = new URLSearchParams({ page: _taskCurrentPage, page_size: 20 });
  if (tenantId) params.set('tenant_id', tenantId);
  if (status) params.set('status', status);
  if (opType) params.set('operation_type', opType);

  try {
    const resp = await fetch(`/admin/api/task-details?${params}`, { credentials: 'include' });
    if (!resp.ok) return;
    const data = await resp.json();

    const tbody = document.querySelector('#task-detail-table tbody');
    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-secondary)">暂无任务</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(item => `
        <tr>
          <td><code>${item.operation_id.substring(0,8)}...</code></td>
          <td>${escapeHtml(item.operation_type)}</td>
          <td>${escapeHtml(item.status)}</td>
          <td>${item.retry_count}</td>
          <td>${escapeHtml(item.worker_id || '-')}</td>
          <td>${formatDate(item.created_at)}</td>
          <td>${formatDate(item.updated_at)}</td>
          <td>${item.error_message ? escapeHtml(item.error_message.substring(0, 50)) : '-'}</td>
        </tr>
      `).join('');
    }

    const totalPages = Math.ceil(data.total / data.page_size) || 1;
    document.getElementById('task-pagination').innerHTML = totalPages <= 1 ? '' :
      `<button class="btn btn-ghost btn-sm" ${data.page <= 1 ? 'disabled' : ''} onclick="_taskCurrentPage--;loadTaskDetails()">上一页</button>
       <span style="margin:0 8px">${data.page} / ${totalPages}</span>
       <button class="btn btn-ghost btn-sm" ${data.page >= totalPages ? 'disabled' : ''} onclick="_taskCurrentPage++;loadTaskDetails()">下一页</button>`;
  } catch (e) {
    console.error('Failed to load task details:', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadTaskStats();
  loadTaskDetails();

  const filterTenant = document.getElementById('filter-tenant');
  const filterStatus = document.getElementById('filter-status');
  const filterType = document.getElementById('filter-type');
  if (filterTenant) filterTenant.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
  if (filterStatus) filterStatus.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
  if (filterType) filterType.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
});
