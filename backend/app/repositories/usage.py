from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models.ai_call import AICall
from app.models.usage import (
    EmbeddingDailyUsage,
    VisionDailyUsage,
)


class VisionBudgetExceededError(Exception):
    pass


class EmbeddingBudgetExceededError(Exception):
    pass


def _reserve_call(
    tenant_id,
    daily_limit,
    usage_table,
    exceeded_error,
    operation,
    call_record,
):
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 50
    ):
        raise ValueError("tenant_id must contain 1 to 50 characters")

    if (
        isinstance(daily_limit, bool)
        or not isinstance(daily_limit, int)
        or daily_limit < 0
    ):
        raise ValueError("daily_limit must be a nonnegative integer")

    if daily_limit == 0:
        raise exceeded_error(f"{operation} calls are disabled")

    with SessionLocal.begin() as session:
        usage_date = session.scalar(
            select(
                cast(
                    func.timezone("UTC", func.current_timestamp()),
                    Date,
                )
            )
        )

        statement = (
            insert(usage_table)
            .values(
                tenant_id=tenant_id,
                usage_date=usage_date,
                calls_reserved=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    usage_table.tenant_id,
                    usage_table.usage_date,
                ],
                set_={
                    "calls_reserved":
                        usage_table.calls_reserved + 1,
                },
                where=(
                    usage_table.calls_reserved < daily_limit
                ),
            )
            .returning(usage_table.calls_reserved)
        )

        reserved_count = session.execute(
            statement
        ).scalar_one_or_none()

        if reserved_count is None:
            raise exceeded_error(
                f"Daily {operation} call limit reached"
            )

        if call_record is not None:
            if call_record.get("tenant_id") != tenant_id:
                raise ValueError(
                    "Call record tenant differs from reservation tenant"
                )

            if call_record.get("operation") != operation:
                raise ValueError("Call record operation differs")

            if call_record.get("status") != "started":
                raise ValueError("New call record must have started status")

            has_image = bool(call_record.get("image_id"))
            has_post = bool(call_record.get("post_id"))

            if has_image == has_post:
                raise ValueError(
                    "Call record must identify exactly one source"
                )

            if operation == "vision" and not has_image:
                raise ValueError("Vision calls require an image source")

            session.add(AICall(**call_record))

    return reserved_count


def reserve_vision_call(
    tenant_id: str,
    daily_limit: int,
    *,
    call_record: dict | None = None,
) -> int:
    return _reserve_call(
        tenant_id=tenant_id,
        daily_limit=daily_limit,
        usage_table=VisionDailyUsage,
        exceeded_error=VisionBudgetExceededError,
        operation="vision",
        call_record=call_record,
    )


def reserve_embedding_call(
    tenant_id: str,
    daily_limit: int,
    *,
    call_record: dict,
) -> int:
    if call_record is None:
        raise ValueError("Embedding calls require an audit record")

    return _reserve_call(
        tenant_id=tenant_id,
        daily_limit=daily_limit,
        usage_table=EmbeddingDailyUsage,
        exceeded_error=EmbeddingBudgetExceededError,
        operation="embedding",
        call_record=call_record,
    )