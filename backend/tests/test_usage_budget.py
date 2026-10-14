from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models.usage import VisionDailyUsage
from app.repositories import usage


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

    tenant_id = f"test-{uuid4()}"

    try:
        yield tenant_id, factory
    finally:
        transaction.rollback()
        connection.close()


def stored_count(factory, tenant_id):
    with factory() as session:
        return session.scalar(
            select(VisionDailyUsage.calls_reserved).where(
                VisionDailyUsage.tenant_id == tenant_id
            )
        )


def test_limit_blocks_extra_call_without_increment(budget_database):
    tenant_id, factory = budget_database

    assert usage.reserve_vision_call(tenant_id, 2) == 1
    assert usage.reserve_vision_call(tenant_id, 2) == 2

    with pytest.raises(usage.VisionBudgetExceededError):
        usage.reserve_vision_call(tenant_id, 2)

    assert stored_count(factory, tenant_id) == 2


def test_zero_limit_creates_no_reservation(budget_database):
    tenant_id, factory = budget_database

    with pytest.raises(usage.VisionBudgetExceededError):
        usage.reserve_vision_call(tenant_id, 0)

    assert stored_count(factory, tenant_id) is None


def test_tenants_have_separate_allowances(budget_database):
    tenant_id, factory = budget_database
    other_tenant = f"test-{uuid4()}"

    assert usage.reserve_vision_call(tenant_id, 1) == 1

    with pytest.raises(usage.VisionBudgetExceededError):
        usage.reserve_vision_call(tenant_id, 1)

    assert usage.reserve_vision_call(other_tenant, 1) == 1

    assert stored_count(factory, tenant_id) == 1
    assert stored_count(factory, other_tenant) == 1


def test_lowered_limit_blocks_existing_usage(budget_database):
    tenant_id, factory = budget_database

    assert usage.reserve_vision_call(tenant_id, 3) == 1
    assert usage.reserve_vision_call(tenant_id, 3) == 2

    with pytest.raises(usage.VisionBudgetExceededError):
        usage.reserve_vision_call(tenant_id, 1)

    assert stored_count(factory, tenant_id) == 2