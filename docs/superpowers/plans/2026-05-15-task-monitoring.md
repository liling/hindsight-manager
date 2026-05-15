# Task Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cross-tenant async operation monitoring to the Manager Dashboard — global stats, per-tenant breakdown, and filterable task detail list.

**Architecture:** Manager queries PostgreSQL directly using raw SQL across tenant schemas. Two new admin API endpoints in a new router file. Frontend adds a tab to the existing Dashboard page with three sections (overview cards, tenant table, detail list).

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, Jinja2 templates, vanilla JS

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `hindsight_manager/api/task_monitor.py` | Two admin API endpoints for task stats and detail |
| Modify | `hindsight_manager/main.py:14,87` | Register new task_monitor router |
| Modify | `hindsight_manager/templates/dashboard.html` | Add tab bar + task monitor section |
| Modify | `hindsight_manager/static/app.js` | Add task monitor JS functions |
| Create | `tests/test_task_monitor.py` | Tests for both endpoints |

---

### Task 1: Backend — task stats endpoint

**Files:**
- Create: `hindsight_manager/api/task_monitor.py`
- Test: `tests/test_task_monitor.py`

- [ ] **Step 1: Write the failing test for `GET /admin/api/task-stats`**

```python
# tests/test_task_monitor.py
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret")

from hindsight_manager.main import app
from hindsight_manager.db import get_session
from hindsight_manager.models.user import UserRole


def _make_admin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.username = "admin"
    u.display_name = "Admin"
    u.role = UserRole.ADMIN
    u.is_active = True
    u.email = "admin@test.com"
    u.auth_provider = MagicMock(value="local")
    return u


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def admin_client():
    admin_user = _make_admin()
    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return admin_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, mock_session
    app.dependency_overrides.clear()


async def test_task_stats_returns_global_and_per_tenant(admin_client):
    client, mock_session = admin_client

    # Mock: tenant list query
    tenant_row = MagicMock()
    tenant_row.id = uuid.uuid4()
    tenant_row.name = "测试租户"
    tenant_row.schema_name = "tenant_test"

    tenant_result = MagicMock()
    tenant_result.scalars.return_value.all.return_value = [tenant_row]
    # First call = tenants, second call = stats per tenant
    mock_session.execute.side_effect = [
        tenant_result,
        # Stats query result for this tenant
        MagicMock(fetchall=lambda: [("pending", 5), ("processing", 2), ("completed", 100)]),
    ]

    resp = await client.get("/admin/api/task-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "global" in data
    assert "by_tenant" in data
    assert data["global"]["pending"] == 5
    assert data["global"]["processing"] == 2
    assert data["global"]["completed"] == 100
    assert len(data["by_tenant"]) == 1
    assert data["by_tenant"][0]["tenant_name"] == "测试租户"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_monitor.py::test_task_stats_returns_global_and_per_tenant -v`
Expected: FAIL (no module `hindsight_manager.api.task_monitor`)

- [ ] **Step 3: Implement `task_monitor.py` with the stats endpoint**

```python
# hindsight_manager/api/task_monitor.py
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import require_admin
from hindsight_manager.db import get_session
from hindsight_manager.models.tenant import Tenant, TenantStatus
from hindsight_manager.models.user import User

router = APIRouter(prefix="/admin/api", tags=["task-monitor"])

STATUSES = ("pending", "processing", "completed", "failed", "cancelled")


class _TenantStats(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class _TenantEntry(BaseModel):
    tenant_id: str
    tenant_name: str
    stats: _TenantStats


class TaskStatsResponse(BaseModel):
    global_: _TenantStats = _TenantStats()
    by_tenant: list[_TenantEntry] = []


@router.get("/task-stats")
async def get_task_stats(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    # Fetch all active tenants
    result = await session.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    )
    tenants = result.scalars().all()

    global_counts: dict[str, int] = defaultdict(int)
    by_tenant: list[_TenantEntry] = []

    for tenant in tenants:
        stats_sql = text("SELECT status, COUNT(*) AS cnt FROM async_operations GROUP BY status")
        # Switch to tenant schema
        await session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
        stats_result = await session.execute(stats_sql)
        # Reset search_path
        await session.execute(text("SET search_path TO public"))

        row_counts: dict[str, int] = {}
        for row in stats_result.fetchall():
            row_counts[row[0]] = row[1]

        tenant_stats = _TenantStats(
            pending=row_counts.get("pending", 0),
            processing=row_counts.get("processing", 0),
            completed=row_counts.get("completed", 0),
            failed=row_counts.get("failed", 0),
            cancelled=row_counts.get("cancelled", 0),
        )

        by_tenant.append(
            _TenantEntry(
                tenant_id=str(tenant.id),
                tenant_name=tenant.name,
                stats=tenant_stats,
            )
        )

        for s in STATUSES:
            global_counts[s] += row_counts.get(s, 0)

    return TaskStatsResponse(
        global_=_TenantStats(**{s: global_counts[s] for s in STATUSES}),
        by_tenant=by_tenant,
    )
```

- [ ] **Step 4: Register the router in main.py**

In `hindsight_manager/main.py`, add the import after the existing router imports (line ~22):

```python
from hindsight_manager.api.task_monitor import router as task_monitor_router
```

Add the router registration after existing `app.include_router` lines (line ~94):

```python
app.include_router(task_monitor_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_task_monitor.py::test_task_stats_returns_global_and_per_tenant -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hindsight_manager/api/task_monitor.py hindsight_manager/main.py tests/test_task_monitor.py
git commit -m "feat: add GET /admin/api/task-stats endpoint for cross-tenant task monitoring"
```

---

### Task 2: Backend — task details endpoint

**Files:**
- Modify: `hindsight_manager/api/task_monitor.py`
- Modify: `tests/test_task_monitor.py`

- [ ] **Step 1: Write the failing test for `GET /admin/api/task-details`**

Append to `tests/test_task_monitor.py`:

```python
async def test_task_details_returns_paginated_items(admin_client):
    client, mock_session = admin_client

    # Mock: tenant lookup
    tenant_row = MagicMock()
    tenant_row.id = uuid.uuid4()
    tenant_row.name = "测试租户"
    tenant_row.schema_name = "tenant_test"

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant_row

    # Mock: count query
    count_row = MagicMock()
    count_row.__getitem__ = lambda self, key: 1
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    # Mock: data query
    op_row = MagicMock()
    op_row.operation_id = uuid.uuid4()
    op_row.operation_type = "consolidation"
    op_row.status = "processing"
    op_row.retry_count = 0
    op_row.worker_id = "worker-1"
    op_row.created_at = "2026-05-15T10:00:00"
    op_row.updated_at = "2026-05-15T10:01:00"
    op_row.completed_at = None
    op_row.error_message = None

    data_result = MagicMock()
    data_result.fetchall.return_value = [op_row]

    mock_session.execute.side_effect = [tenant_result, count_result, data_result]

    resp = await client.get(
        "/admin/api/task-details",
        params={"tenant_id": str(tenant_row.id), "page": 1, "page_size": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["operation_type"] == "consolidation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_monitor.py::test_task_details_returns_paginated_items -v`
Expected: FAIL (404 — endpoint not yet implemented)

- [ ] **Step 3: Add the details endpoint to `task_monitor.py`**

Append to `hindsight_manager/api/task_monitor.py`:

```python
class TaskDetailItem(BaseModel):
    operation_id: str
    tenant_id: str
    tenant_name: str
    operation_type: str
    status: str
    retry_count: int
    worker_id: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None
    error_message: str | None


class TaskDetailsResponse(BaseModel):
    items: list[TaskDetailItem]
    total: int
    page: int
    page_size: int


@router.get("/task-details")
async def get_task_details(
    tenant_id: str | None = Query(None),
    status: str | None = Query(None),
    operation_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if tenant_id:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return TaskDetailsResponse(items=[], total=0, page=page, page_size=page_size)
        tenants = [tenant]
    else:
        result = await session.execute(
            select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
        )
        tenants = result.scalars().all()

    offset = (page - 1) * page_size
    all_items: list[TaskDetailItem] = []
    total_count = 0

    for tenant in tenants:
        conditions = []
        if status:
            conditions.append(f"status = '{status}'")
        if operation_type:
            conditions.append(f"operation_type = '{operation_type}'")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Count
        await session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
        count_result = await session.execute(text(f"SELECT COUNT(*) FROM async_operations {where_clause}"))
        total_count += count_result.scalar()

        # Data
        data_result = await session.execute(
            text(
                f"SELECT operation_id, operation_type, status, retry_count, worker_id, "
                f"created_at, updated_at, completed_at, error_message "
                f"FROM async_operations {where_clause} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"limit": page_size, "offset": offset},
        )
        await session.execute(text("SET search_path TO public"))

        for row in data_result.fetchall():
            all_items.append(
                TaskDetailItem(
                    operation_id=str(row[0]),
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name,
                    operation_type=row[1],
                    status=row[2],
                    retry_count=row[3],
                    worker_id=row[4],
                    created_at=str(row[5]) if row[5] else None,
                    updated_at=str(row[6]) if row[6] else None,
                    completed_at=str(row[7]) if row[7] else None,
                    error_message=row[8],
                )
            )

    return TaskDetailsResponse(items=all_items, total=total_count, page=page, page_size=page_size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_task_monitor.py::test_task_details_returns_paginated_items -v`
Expected: PASS

- [ ] **Step 5: Run all task monitor tests**

Run: `uv run pytest tests/test_task_monitor.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add hindsight_manager/api/task_monitor.py tests/test_task_monitor.py
git commit -m "feat: add GET /admin/api/task-details endpoint with filtering and pagination"
```

---

### Task 3: Frontend — HTML structure (tab bar + task monitor section)

**Files:**
- Modify: `hindsight_manager/templates/dashboard.html`

- [ ] **Step 1: Add tab bar HTML and task monitor section to dashboard.html**

Replace the entire `{% block main %}` content in `dashboard.html` with the following. Keep the existing CSS classes and patterns.

Wrap the `<button class="btn btn-primary" onclick="showCreateModal()">+ 创建记忆库</button>` and everything up to `{% endblock %}` in the new tab structure:

After `<div class="content-header">`:
- Replace with a `<div class="content-header">` containing the title and a tab bar `<div class="tab-bar">` with two buttons: "我的租户" (active by default via `class="tab-btn active"`) and "任务监控".

Then the existing usage guide + tenant list stays inside `<div id="tab-tenants" class="tab-content">`.

Add a new `<div id="tab-tasks" class="tab-content" style="display:none">` containing three subsections:

```html
<!-- Task monitor: global stats cards -->
<div class="task-stats-cards">
  <div class="task-stat-card" data-status="pending">
    <div class="task-stat-number" id="stat-pending">-</div>
    <div class="task-stat-label">待处理</div>
  </div>
  <div class="task-stat-card card-processing">
    <div class="task-stat-number" id="stat-processing">-</div>
    <div class="task-stat-label">处理中</div>
  </div>
  <div class="task-stat-card card-completed">
    <div class="task-stat-number" id="stat-completed">-</div>
    <div class="task-stat-label">已完成</div>
  </div>
  <div class="task-stat-card card-failed">
    <div class="task-stat-number" id="stat-failed">-</div>
    <div class="task-stat-label">失败</div>
  </div>
  <div class="task-stat-card card-cancelled">
    <div class="task-stat-number" id="stat-cancelled">-</div>
    <div class="task-stat-label">已取消</div>
  </div>
</div>

<!-- Task monitor: per-tenant table -->
<div class="task-section">
  <div class="task-section-header">
    <h3>按租户统计</h3>
  </div>
  <table class="task-table" id="task-tenant-table">
    <thead>
      <tr>
        <th>租户名称</th>
        <th>待处理</th>
        <th>处理中</th>
        <th>已完成</th>
        <th>失败</th>
        <th>已取消</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</div>

<!-- Task monitor: detail list -->
<div class="task-section">
  <div class="task-section-header">
    <h3>任务详情</h3>
    <div class="task-filters">
      <select id="filter-tenant"><option value="">全部租户</option></select>
      <select id="filter-status">
        <option value="">全部状态</option>
        <option value="pending">待处理</option>
        <option value="processing">处理中</option>
        <option value="completed">已完成</option>
        <option value="failed">失败</option>
        <option value="cancelled">已取消</option>
      </select>
      <select id="filter-type">
        <option value="">全部类型</option>
        <option value="retain">retain</option>
        <option value="consolidation">consolidation</option>
        <option value="refresh_mental_model">refresh_mental_model</option>
        <option value="file_convert_retain">file_convert_retain</option>
        <option value="webhook_delivery">webhook_delivery</option>
        <option value="batch_retain">batch_retain</option>
      </select>
      <button class="btn btn-secondary btn-sm" onclick="loadTaskDetails()">刷新</button>
    </div>
  </div>
  <table class="task-table" id="task-detail-table">
    <thead>
      <tr>
        <th>操作 ID</th>
        <th>类型</th>
        <th>状态</th>
        <th>重试</th>
        <th>Worker</th>
        <th>创建时间</th>
        <th>更新时间</th>
        <th>错误信息</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
  <div class="task-pagination" id="task-pagination"></div>
</div>
```

Place the two existing modals (create-modal, apikey-modal) outside both tab-content divs.

- [ ] **Step 2: Add inline CSS for the new elements**

In the `<style>` section (or in a `<style>` block added before the closing `{% endblock %}`), add styles for: `.tab-bar`, `.tab-btn`, `.task-stats-cards`, `.task-stat-card` (and color variants), `.task-section`, `.task-table`, `.task-filters`, `.task-pagination`. Use the existing CSS variable names from `admin_base.html` / `base.html` (e.g., `var(--primary)`, `var(--bg-card)`, etc.).

- [ ] **Step 3: Visually verify in browser**

Run: `uvicorn hindsight_manager.main:app --reload --port 8001`
Open: `http://localhost:8001/dashboard`
Expected: Tab bar visible, "任务监控" tab shows cards/tables (empty). "我的租户" tab shows existing content.

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/templates/dashboard.html
git commit -m "feat: add task monitor tab and HTML structure to dashboard"
```

---

### Task 4: Frontend — JavaScript logic

**Files:**
- Modify: `hindsight_manager/static/app.js`

- [ ] **Step 1: Add tab switching and data loading functions to app.js**

Append the following functions to the end of `hindsight_manager/static/app.js`:

```javascript
// === Task Monitor ===

let _taskCurrentPage = 1;
let _taskFilterTenant = '';

function switchTab(tab) {
  document.getElementById('tab-tenants').style.display = tab === 'tenants' ? 'block' : 'none';
  document.getElementById('tab-tasks').style.display = tab === 'tasks' ? 'block' : 'none';
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'tasks') {
    loadTaskStats();
    loadTaskDetails();
  }
}

async function loadTaskStats() {
  try {
    const resp = await fetch('/admin/api/task-stats', { credentials: 'include' });
    if (!resp.ok) return;
    const data = await resp.json();

    const g = data.global_;
    document.getElementById('stat-pending').textContent = g.pending;
    document.getElementById('stat-processing').textContent = g.processing;
    document.getElementById('stat-completed').textContent = g.completed;
    document.getElementById('stat-failed').textContent = g.failed;
    document.getElementById('stat-cancelled').textContent = g.cancelled;

    // Per-tenant table
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

    // Populate tenant filter dropdown
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
  _taskFilterTenant = tenantId;
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

    // Pagination
    const totalPages = Math.ceil(data.total / data.page_size) || 1;
    document.getElementById('task-pagination').innerHTML = totalPages <= 1 ? '' :
      `<button class="btn btn-ghost btn-sm" ${data.page <= 1 ? 'disabled' : ''} onclick="_taskCurrentPage--;loadTaskDetails()">上一页</button>
       <span style="margin:0 8px">${data.page} / ${totalPages}</span>
       <button class="btn btn-ghost btn-sm" ${data.page >= totalPages ? 'disabled' : ''} onclick="_taskCurrentPage++;loadTaskDetails()">下一页</button>`;
  } catch (e) {
    console.error('Failed to load task details:', e);
  }
}
```

- [ ] **Step 2: Wire up filter change events**

Add event listeners at the bottom of `app.js` (or inside a `DOMContentLoaded` block):

```javascript
document.addEventListener('DOMContentLoaded', () => {
  const filterTenant = document.getElementById('filter-tenant');
  const filterStatus = document.getElementById('filter-status');
  const filterType = document.getElementById('filter-type');
  if (filterTenant) filterTenant.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
  if (filterStatus) filterStatus.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
  if (filterType) filterType.addEventListener('change', () => { _taskCurrentPage = 1; loadTaskDetails(); });
});
```

- [ ] **Step 3: Visually verify in browser**

Run: `uvicorn hindsight_manager.main:app --reload --port 8001`
Open: `http://localhost:8001/dashboard`, click "任务监控" tab.
Expected: Tab switches. Overview cards show "0" (if no data) or real counts if connected to a DB with tenants. Tables render. Filters work. Pagination shows when needed.

- [ ] **Step 4: Commit**

```bash
git add hindsight_manager/static/app.js
git commit -m "feat: add task monitor JavaScript logic for stats and detail loading"
```

---

### Task 5: Integration test — both endpoints + non-admin rejection

**Files:**
- Modify: `tests/test_task_monitor.py`

- [ ] **Step 1: Add non-admin rejection tests**

Append to `tests/test_task_monitor.py`:

```python
@pytest.fixture
async def normal_client():
    normal_user = MagicMock()
    normal_user.id = uuid.uuid4()
    normal_user.username = "normal"
    normal_user.display_name = "Normal"
    normal_user.role = UserRole.USER
    normal_user.is_active = True
    normal_user.email = "normal@test.com"
    normal_user.auth_provider = MagicMock(value="local")

    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    async def _override_current_user():
        return normal_user

    from hindsight_manager.auth.dependencies import get_current_user
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_task_stats_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.get("/admin/api/task-stats")
    assert resp.status_code == 403


async def test_task_details_requires_admin(normal_client: AsyncClient):
    resp = await normal_client.get("/admin/api/task-details")
    assert resp.status_code == 403


async def test_task_stats_empty_when_no_tenants(admin_client):
    client, mock_session = admin_client
    tenant_result = MagicMock()
    tenant_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = tenant_result

    resp = await client.get("/admin/api/task-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["global"]["pending"] == 0
    assert data["by_tenant"] == []


async def test_task_details_empty_when_no_tenant_match(admin_client):
    client, mock_session = admin_client
    # session.get for Tenant returns None (not found)
    mock_session.get = AsyncMock(return_value=None)

    resp = await client.get(
        "/admin/api/task-details",
        params={"tenant_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
```

- [ ] **Step 2: Run all task monitor tests**

Run: `uv run pytest tests/test_task_monitor.py -v`
Expected: All 6 tests PASS (2 existing + 4 new)

- [ ] **Step 3: Commit**

```bash
git add tests/test_task_monitor.py
git commit -m "test: add permission tests and edge cases for task monitoring endpoints"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 2: Manual smoke test in browser**

Run: `uvicorn hindsight_manager.main:app --reload --port 8001` (connected to a real DB if available)

1. Login as admin, navigate to `/dashboard`
2. Click "任务监控" tab — verify cards show counts, tenant table populates, detail list loads
3. Click a tenant row — verify detail list filters to that tenant
4. Use the filter dropdowns — verify results update
5. Test pagination if enough tasks exist
6. Verify "我的租户" tab still works correctly (no regression)

- [ ] **Step 3: Final commit (if any fixes needed during smoke test)**
