import enum
import uuid

from sqlalchemy import Enum, ForeignKey, PrimaryKeyConstraint
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

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role", schema="manager"), nullable=False, default=MemberRole.MEMBER
    )
    created_at: Mapped[str] = mapped_column(server_default="now()")

    user: Mapped["User"] = relationship(back_populates="memberships")
    tenant: Mapped["Tenant"] = relationship(back_populates="members")
