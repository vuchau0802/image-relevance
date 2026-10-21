from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default=lambda: f"ws_{uuid4().hex}",
    )

    auth_issuer: Mapped[str] = mapped_column(String(512))
    auth_user_id: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "auth_issuer",
            "auth_user_id",
            name="uq_workspaces_account",
        ),
        CheckConstraint(
            "length(trim(auth_issuer)) > 0",
            name="ck_workspaces_issuer_nonblank",
        ),
        CheckConstraint(
            "length(trim(auth_user_id)) > 0",
            name="ck_workspaces_user_nonblank",
        ),
    )