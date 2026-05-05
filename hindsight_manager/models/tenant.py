import enum
import uuid

from sqlalchemy import Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETING = "deleting"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status"), nullable=False, default=TenantStatus.ACTIVE
    )
    created_at: Mapped[str] = mapped_column(server_default="now()")

    members: Mapped[list["TenantMember"]] = relationship(back_populates="tenant")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="tenant")
