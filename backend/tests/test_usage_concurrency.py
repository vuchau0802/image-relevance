from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.usage import VisionDailyUsage
from app.repositories.usage import (
    VisionBudgetExceededError,
    reserve_vision_call,
)


def test_concurrent_reservations_respect_limit():
    tenant = f"test-{uuid4()}"
    barrier = Barrier(4)

    def reserve():
        barrier.wait(timeout=10)

        try:
            reserve_vision_call(tenant, daily_limit=2)
            return True
        except VisionBudgetExceededError:
            return False

    try:
        # Each thread uses its own database session.
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(reserve) for _ in range(4)]
            results = [future.result(timeout=20) for future in futures]

        assert results.count(True) == 2
        assert results.count(False) == 2

        with SessionLocal() as session:
            counts = session.scalars(
                select(VisionDailyUsage.calls_reserved).where(
                    VisionDailyUsage.tenant_id == tenant
                )
            ).all()

        assert counts == [2]

    finally:
        # Remove only this test tenant's committed usage.
        with SessionLocal.begin() as session:
            session.execute(
                delete(VisionDailyUsage).where(
                    VisionDailyUsage.tenant_id == tenant
                )
            )