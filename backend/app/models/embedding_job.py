from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    Index,
    Text,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmbeddingJob(Base):
    __tablename__ = "embedding_jobs"

    tenant_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    dimensions: Mapped[int] = mapped_column(
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="queued",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_embedding_jobs_tenant_idempotency",
        ),
        CheckConstraint(
            "status IN "
            "('queued', 'running', 'completed', "
            "'completed_with_errors', 'failed')",
            name="ck_embedding_jobs_status",
        ),
        CheckConstraint(
            "dimensions BETWEEN 1 AND 3072",
            name="ck_embedding_jobs_dimensions",
        ),
        CheckConstraint(
            "task_type = 'SEMANTIC_SIMILARITY'",
            name="ck_embedding_jobs_task_type",
        ),
        CheckConstraint(
            "length(trim(model)) > 0",
            name="ck_embedding_jobs_model_nonblank",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_embedding_jobs_idempotency_nonblank",
        ),
    )

class EmbeddingJobItem(Base):
    __tablename__ = "embedding_job_items"

    tenant_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    input_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        nullable=False,
        server_default="3",
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    claim_token: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    cache_hit: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["embedding_jobs.tenant_id", "embedding_jobs.id"],
            name="fk_embedding_items_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "source_type",
            "source_id",
            name="uq_embedding_items_job_source",
        ),
        CheckConstraint(
            "source_type IN ('image', 'post')",
            name="ck_embedding_items_source_type",
        ),
        CheckConstraint(
            "length(trim(source_id)) > 0",
            name="ck_embedding_items_source_nonblank",
        ),
        CheckConstraint(
            "length(trim(input_text)) > 0",
            name="ck_embedding_items_text_nonblank",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_embedding_items_input_hash",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'processing', 'completed', 'failed')",
            name="ck_embedding_items_status",
        ),
        CheckConstraint(
            "max_attempts >= 1 "
            "AND attempts >= 0 "
            "AND attempts <= max_attempts",
            name="ck_embedding_items_attempts",
        ),
        CheckConstraint(
            "(status = 'processing' "
            "AND claim_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) "
            "OR "
            "(status <> 'processing' "
            "AND claim_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_embedding_items_claim",
        ),
        Index(
            "ix_embedding_items_ready",
            "tenant_id",
            "job_id",
            "status",
            "available_at",
        ),
    )