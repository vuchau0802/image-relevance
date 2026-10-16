from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import engine, SessionLocal
from app.models import AICall, EmbeddingDailyUsage, VisionDailyUsage
from app.repositories import usage


pytestmark = pytest.mark.integration


@pytest.fixture
def budget_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(usage, "SessionLocal", factory)

    try:
        yield f"test-{uuid4()}", factory
    finally:
        transaction.rollback()
        connection.close()


def call_record(tenant, **changes):
    data = {
        "tenant_id": tenant,
        "call_id": str(uuid4()),
        "image_id": "test_image",
        "post_id": None,
        "operation": "embedding",
        "model": "test-embedding-model",
        "status": "started",
        "estimated_cost_usd": 0.0,
        "cost_basis": "Test fixture",
    }
    return data | changes


def reserved_count(factory, table, tenant):
    with factory() as session:
        return session.scalar(
            select(table.calls_reserved).where(
                table.tenant_id == tenant
            )
        )


def audit_count(factory, tenant):
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(AICall)
            .where(AICall.tenant_id == tenant)
        )


def test_limit_blocks_extra_call_and_audit(budget_database):
    tenant, factory = budget_database

    usage.reserve_embedding_call(
        tenant, 1, call_record=call_record(tenant)
    )

    with pytest.raises(usage.EmbeddingBudgetExceededError):
        usage.reserve_embedding_call(
            tenant, 1, call_record=call_record(tenant)
        )

    assert reserved_count(factory, EmbeddingDailyUsage, tenant) == 1
    assert audit_count(factory, tenant) == 1


def test_zero_limit_creates_nothing(budget_database):
    tenant, factory = budget_database

    with pytest.raises(usage.EmbeddingBudgetExceededError):
        usage.reserve_embedding_call(
            tenant, 0, call_record=call_record(tenant)
        )

    assert reserved_count(factory, EmbeddingDailyUsage, tenant) is None
    assert audit_count(factory, tenant) == 0


def test_post_attribution_and_independent_vision_allowance(
    budget_database,
):
    tenant, factory = budget_database

    usage.reserve_vision_call(tenant, 1)

    record = call_record(
        tenant,
        image_id=None,
        post_id="test_post",
    )
    usage.reserve_embedding_call(tenant, 1, call_record=record)

    assert reserved_count(factory, VisionDailyUsage, tenant) == 1
    assert reserved_count(factory, EmbeddingDailyUsage, tenant) == 1

    with factory() as session:
        stored = session.get(AICall, (tenant, record["call_id"]))
        assert stored.image_id is None
        assert stored.post_id == "test_post"
        assert stored.operation == "embedding"
        assert stored.status == "started"


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "different-tenant"},
        {"post_id": "test_post"},
        {"image_id": None},
        {"operation": "vision"},
        {"status": "completed"},
    ],
)
def test_invalid_audit_rolls_back_reservation(
    budget_database,
    changes,
):
    tenant, factory = budget_database

    with pytest.raises(ValueError):
        usage.reserve_embedding_call(
            tenant,
            2,
            call_record=call_record(tenant, **changes),
        )

    assert reserved_count(factory, EmbeddingDailyUsage, tenant) is None
    assert audit_count(factory, tenant) == 0


def test_database_insert_failure_rolls_back_increment(budget_database):
    tenant, factory = budget_database
    record = call_record(tenant)

    usage.reserve_embedding_call(tenant, 3, call_record=record)

    # Reusing the same call ID violates the audit primary key.
    with pytest.raises(IntegrityError):
        usage.reserve_embedding_call(tenant, 3, call_record=record)

    assert reserved_count(factory, EmbeddingDailyUsage, tenant) == 1
    assert audit_count(factory, tenant) == 1


def test_tenants_have_separate_allowances(budget_database):
    tenant, factory = budget_database
    other = f"test-{uuid4()}"

    usage.reserve_embedding_call(
        tenant, 1, call_record=call_record(tenant)
    )

    with pytest.raises(usage.EmbeddingBudgetExceededError):
        usage.reserve_embedding_call(
            tenant, 1, call_record=call_record(tenant)
        )

    usage.reserve_embedding_call(
        other, 1, call_record=call_record(other)
    )

    assert reserved_count(factory, EmbeddingDailyUsage, tenant) == 1
    assert reserved_count(factory, EmbeddingDailyUsage, other) == 1


def test_concurrent_embedding_reservations_respect_limit():
    tenant = f"test-{uuid4()}"
    barrier = Barrier(4)

    def reserve():
        barrier.wait(timeout=10)

        try:
            usage.reserve_embedding_call(
                tenant,
                2,
                call_record=call_record(tenant),
            )
            return True
        except usage.EmbeddingBudgetExceededError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(reserve) for _ in range(4)]
            results = [
                future.result(timeout=20)
                for future in futures
            ]

        assert results.count(True) == 2
        assert results.count(False) == 2
        assert reserved_count(
            SessionLocal, EmbeddingDailyUsage, tenant
        ) == 2
        assert audit_count(SessionLocal, tenant) == 2

    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(AICall).where(AICall.tenant_id == tenant)
            )
            session.execute(
                delete(EmbeddingDailyUsage).where(
                    EmbeddingDailyUsage.tenant_id == tenant
                )
            )