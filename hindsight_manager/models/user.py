import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hindsight_manager.models.base import Base


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    CAS = "cas"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider", schema="manager"), nullable=False
    )
    # NOTE: Type inconsistency - created_at uses Mapped[str] while updated_at uses Mapped[datetime]
    # This is a legacy issue that should be fixed in a future migration to ensure consistency
    created_at: Mapped[str] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), server_default="true", nullable=False)

    memberships: Mapped[list["TenantMember"]] = relationship(back_populates="user")
