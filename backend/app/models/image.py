from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Image(Base):
    __tablename__ = "images"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )

    file_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))

    source_url: Mapped[str] = mapped_column(Text)
    creator: Mapped[str] = mapped_column(Text)
    license_url: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(20), server_default="pending"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "checksum",
            name="uq_images_tenant_checksum",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'processing', 'completed', "
            "'needs_review', 'failed')",
            name="ck_images_status",
        ),
        Index("ix_images_tenant_status", "tenant_id", "status"),
    )


class ImageMetadataRecord(Base):
    __tablename__ = "image_metadata"

    tenant_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    image_id: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )

    subject: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    attributes: Mapped[list[str]] = mapped_column(JSONB)
    caption: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    vision_model: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "image_id"],
            ["images.tenant_id", "images.id"],
            name="fk_metadata_tenant_image",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_metadata_confidence",
        ),
        CheckConstraint(
            "category IN ('animal', 'vehicle', 'food', 'landscape')",
            name="ck_metadata_category",
        ),
    )