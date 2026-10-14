from datetime import date

from sqlalchemy import CheckConstraint, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VisionDailyUsage(Base):
    __tablename__ = "vision_daily_usage"

    tenant_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )
    usage_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
    )
    calls_reserved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    __table_args__ = (
        CheckConstraint(
            "calls_reserved >= 0",
            name="ck_vision_daily_usage_nonnegative",
        ),
    )