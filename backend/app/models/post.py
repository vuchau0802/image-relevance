from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Post(Base):
    __tablename__ = "posts"

    tenant_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )

    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    required_subject: Mapped[str] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_posts_title_nonblank",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_posts_content_nonblank",
        ),
        CheckConstraint(
            "length(trim(required_subject)) > 0",
            name="ck_posts_subject_nonblank",
        ),
    )