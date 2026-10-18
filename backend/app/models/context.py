from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PostContextRecord(Base):
    __tablename__ = "post_context"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    post_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    input_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    version: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )

    requirements: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="needs_review",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "post_id"],
            ["posts.tenant_id", "posts.id"],
            name="fk_post_context_post",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_post_context_input_hash",
        ),
        CheckConstraint(
            "length(trim(version)) > 0",
            name="ck_post_context_version",
        ),
        CheckConstraint(
            "jsonb_typeof(requirements) = 'object'",
            name="ck_post_context_requirements",
        ),
        CheckConstraint(
            "review_status IN ('needs_review', 'reviewed')",
            name="ck_post_context_review_status",
        ),
    )


class ImageContextRecord(Base):
    __tablename__ = "image_context"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    image_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    image_checksum: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    version: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )

    facts: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="needs_review",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "image_id"],
            ["images.tenant_id", "images.id"],
            name="fk_image_context_image",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "image_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_image_context_checksum",
        ),
        CheckConstraint(
            "length(trim(version)) > 0",
            name="ck_image_context_version",
        ),
        CheckConstraint(
            "jsonb_typeof(facts) = 'array'",
            name="ck_image_context_facts",
        ),
        CheckConstraint(
            "review_status IN ('needs_review', 'reviewed')",
            name="ck_image_context_review_status",
        ),
    )