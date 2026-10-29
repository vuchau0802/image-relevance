from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImageFileCleanupTask(Base):
    __tablename__ = "image_file_cleanup_tasks"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    image_id: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(
        String(20), server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="3")
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "image_id",
            name="uq_image_cleanup_source",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_image_cleanup_status",
        ),
        CheckConstraint(
            "max_attempts >= 1 "
            "AND attempts >= 0 "
            "AND attempts <= max_attempts",
            name="ck_image_cleanup_attempts",
        ),
        CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name="ck_image_cleanup_checksum",
        ),
        CheckConstraint(
            "length(trim(file_path)) > 0",
            name="ck_image_cleanup_path",
        ),
        Index(
            "ix_image_cleanup_ready",
            "status",
            "available_at",
        ),
    )