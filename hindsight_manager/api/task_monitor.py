from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
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
    global_: _TenantStats = Field(alias="global", default=_TenantStats())
    by_tenant: list[_TenantEntry] = []

    model_config = {"populate_by_name": True, "by_alias": True}


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
            conditions.append(f"status = :status")
        if operation_type:
            conditions.append(f"operation_type = :op_type")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params = {}
        if status:
            params["status"] = status
        if operation_type:
            params["op_type"] = operation_type

        await session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM async_operations {where_clause}"),
            params if params else None,
        )
        total_count += count_result.scalar()

        query_params = {"limit": page_size, "offset": offset}
        query_params.update(params)
        data_result = await session.execute(
            text(
                f"SELECT operation_id, operation_type, status, retry_count, worker_id, "
                f"created_at, updated_at, completed_at, error_message "
                f"FROM async_operations {where_clause} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            query_params,
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