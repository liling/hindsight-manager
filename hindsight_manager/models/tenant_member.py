import enum
import uuid

from sqlalchemy import Enum, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class MemberRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "tenant_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role", schema="manager",
             values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MemberRole.MEMBER,
        server_default="member",
    )
    created_at: Mapped[str] = mapped_column(server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="members")
