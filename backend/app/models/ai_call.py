from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AICall(Base):
    __tablename__ = "ai_calls"

    tenant_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36))
    job_item_id: Mapped[str | None] = mapped_column(String(36))
    attempt: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), server_default="started")
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, server_default="0")
    cost_basis: Mapped[str] = mapped_column(String(200))
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(image_id IS NOT NULL AND post_id IS NULL) OR "
            "(image_id IS NULL AND post_id IS NOT NULL)",
            name="ck_ai_calls_exactly_one_source",
        ),
        CheckConstraint(
            "status IN ('started', 'completed', 'needs_review', 'failed', 'interrupted')",
            name="ck_ai_calls_status",
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_calls_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_calls_output_tokens"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_ai_calls_cost"),
        Index("ix_ai_calls_tenant_created", "tenant_id", "created_at"),
    )
