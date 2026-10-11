from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_id():
    return str(uuid4())


class Job(Base):
    __tablename__ = "jobs"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(30), server_default="queued"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_jobs_tenant_idempotency",
        ),
        CheckConstraint(
            "status IN "
            "('queued', 'running', 'completed', "
            "'completed_with_errors', 'failed')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
    )


class JobItem(Base):
    __tablename__ = "job_items"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

    job_id: Mapped[str] = mapped_column(String(36))
    image_id: Mapped[str] = mapped_column(String(50))

    status: Mapped[str] = mapped_column(
        String(20), server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="3")

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    claim_token: Mapped[str | None] = mapped_column(String(36))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_items_tenant_job",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "image_id"],
            ["images.tenant_id", "images.id"],
            name="fk_job_items_tenant_image",
        ),
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "image_id",
            name="uq_job_items_job_image",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'processing', 'completed', "
            "'needs_review', 'failed')",
            name="ck_job_items_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1 "
            "AND attempts <= max_attempts",
            name="ck_job_items_attempts",
        ),
        Index(
            "ix_job_items_ready",
            "tenant_id",
            "status",
            "available_at",
        ),
    )