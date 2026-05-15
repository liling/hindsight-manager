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