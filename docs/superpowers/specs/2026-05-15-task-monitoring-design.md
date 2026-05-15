# Task Monitoring Design

## Goal

Provide cross-tenant task monitoring on the Manager Dashboard, so administrators can see at a glance how many async operations are running across all tenants, drill down by tenant, and inspect individual task details.

## Context

Hindsight's data plane stores async operations (tasks) in each tenant's schema under the `async_operations` table. Task types include: `retain`, `consolidation`, `refresh_mental_model`, `file_convert_retain`, `webhook_delivery`, `batch_retain`. States: `pending`, `processing`, `completed`, `failed`, `cancelled`.

The existing data plane API only supports per-bank queries (`/banks/{bank_id}/stats`). There is no cross-tenant aggregation. The Manager Dashboard currently shows only tenant list and basic operations — no task monitoring.

## Approach

Single-page three-area design on the existing Dashboard, with a new "Task Monitor" tab. Manager queries PostgreSQL directly, aggregating `async_operations` across tenant schemas in real time.

## Backend API

### New router: `hindsight_manager/api/task_monitor.py`

Both endpoints require admin access (reuse `require_admin` dependency).

#### `GET /admin/api/task-stats`

Returns aggregated task counts — global and per-tenant.

**Query logic:**
1. Fetch all tenants from `manager.tenants`
2. For each tenant, set `search_path` to the tenant's schema and execute:
   ```sql
   SELECT status, COUNT(*) FROM async_operations GROUP BY status
   ```
3. Aggregate in memory into global totals and per-tenant breakdowns

**Response:**
```json
{
  "global": {
    "pending": 42,
    "processing": 8,
    "completed": 1205,
    "failed": 3,
    "cancelled": 1
  },
  "by_tenant": [
    {
      "tenant_id": "uuid",
      "tenant_name": "租户A",
      "stats": {
        "pending": 10,
        "processing": 2,
        "completed": 300,
        "failed": 1,
        "cancelled": 0
      }
    }
  ]
}
```

#### `GET /admin/api/task-details`

Returns paginated task detail list with optional filters.

**Query parameters:**
- `tenant_id` (optional) — filter to a specific tenant
- `status` (optional) — filter by status
- `operation_type` (optional) — filter by operation type
- `page` (default 1)
- `page_size` (default 20)

**Query logic:**
1. Resolve tenant(s) — if `tenant_id` provided, use that schema; otherwise query all tenant schemas
2. Build filtered query on `async_operations` with WHERE clauses for status/type
3. ORDER BY `created_at DESC`, apply LIMIT/OFFSET pagination

**Response:**
```json
{
  "items": [
    {
      "operation_id": "uuid",
      "tenant_id": "uuid",
      "tenant_name": "租户A",
      "operation_type": "consolidation",
      "status": "processing",
      "retry_count": 0,
      "worker_id": "worker-1",
      "created_at": "2026-05-15T10:00:00Z",
      "updated_at": "2026-05-15T10:01:00Z",
      "completed_at": null,
      "error_message": null
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

## Frontend UI

### Tab bar

Add a tab bar at the top of the Dashboard page with two tabs:
- **我的租户** — existing tenant list content
- **任务监控** — new task monitoring view

### Task Monitor layout (top to bottom)

**1. Global overview cards**

5 status cards in a horizontal row:
| Status | Color |
|--------|-------|
| 待处理 (pending) | Yellow |
| 处理中 (processing) | Blue |
| 已完成 (completed) | Green |
| 失败 (failed) | Red |
| 已取消 (cancelled) | Gray |

Each card shows the status label and count number.

**2. Per-tenant table**

| 租户名称 | 待处理 | 处理中 | 已完成 | 失败 | 已取消 |
|----------|--------|--------|--------|------|--------|

Clicking a row filters the detail list below to that tenant.

**3. Task detail list**

Filter bar with three dropdowns: tenant, status, operation type.

Paginated table:

| 操作ID | 类型 | 状态 | 重试次数 | Worker | 创建时间 | 更新时间 | 错误信息 |
|--------|------|------|---------|--------|---------|---------|---------|

### Implementation notes

- All markup goes in `templates/dashboard.html`
- JavaScript goes in `static/app.js` (append, reuse existing AJAX patterns)
- Reuse existing `admin_base.html` styles and card/table components
- Data fetched on tab switch and on manual refresh button click
