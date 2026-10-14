from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models.usage import VisionDailyUsage


class VisionBudgetExceededError(Exception):
    """The tenant has no remaining vision allowance today."""


def reserve_vision_call(
    tenant_id: str,
    daily_limit: int,
) -> int:
    """Reserve one call and return the new daily count."""
    if not tenant_id or len(tenant_id) > 50:
        raise ValueError("tenant_id must contain 1 to 50 characters")

    if daily_limit < 0:
        raise ValueError("daily_limit must be nonnegative")

    if daily_limit == 0:
        raise VisionBudgetExceededError("Vision calls are disabled")

    with SessionLocal.begin() as session:
        # Use the database clock and UTC for every worker.
        usage_date = session.scalar(
            select(
                cast(
                    func.timezone("UTC", func.current_timestamp()),
                    Date,
                )
            )
        )

        statement = (
            insert(VisionDailyUsage)
            .values(
                tenant_id=tenant_id,
                usage_date=usage_date,
                calls_reserved=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    VisionDailyUsage.tenant_id,
                    VisionDailyUsage.usage_date,
                ],
                set_={
                    "calls_reserved":
                        VisionDailyUsage.calls_reserved + 1,
                },
                where=(
                    VisionDailyUsage.calls_reserved < daily_limit
                ),
            )
            .returning(VisionDailyUsage.calls_reserved)
        )

        reserved_count = session.execute(
            statement
        ).scalar_one_or_none()

        if reserved_count is None:
            raise VisionBudgetExceededError(
                "Daily vision call limit reached"
            )

    return reserved_count