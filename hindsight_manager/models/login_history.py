"""Login history model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from hindsight_manager.models.base import Base


class LoginHistory(Base):
    """Login history tracking model."""

    __tablename__ = "login_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 compatible
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    login_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
