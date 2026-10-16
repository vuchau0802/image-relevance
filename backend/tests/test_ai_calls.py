from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import AICall, VisionDailyUsage
from app.repositories import ai_calls, usage

pytestmark = pytest.mark.integration


@pytest.fixture
def audit_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(usage, "SessionLocal", factory)
    monkeypatch.setattr(ai_calls, "SessionLocal", factory)
    try:
        yield f"test-{uuid4()}", factory
    finally:
        transaction.rollback()
        connection.close()


def record(tenant):
    return dict(
        tenant_id=tenant, call_id=str(uuid4()), image_id="test_image",
        model="test-model", operation="vision", status="started",
        estimated_cost_usd=0.0, cost_basis="Test fixture",
    )


def test_reservation_atomically_creates_audit_and_completion(audit_database):
    tenant, factory = audit_database
    call = record(tenant)
    assert usage.reserve_vision_call(tenant, 1, call_record=call) == 1
    with factory() as session:
        stored = session.get(AICall, (tenant, call["call_id"]))
        assert stored.status == "started"
        assert stored.finished_at is None
    ai_calls.finish_ai_call(tenant, call["call_id"], status="completed", input_tokens=11, output_tokens=5)
    with factory() as session:
        stored = session.get(AICall, (tenant, call["call_id"]))
        assert stored.status == "completed"
        assert stored.input_tokens == 11
        assert stored.output_tokens == 5
        assert stored.finished_at is not None


def test_blocked_allowance_does_not_create_audit(audit_database):
    tenant, factory = audit_database
    usage.reserve_vision_call(tenant, 1)
    call = record(tenant)
    with pytest.raises(usage.VisionBudgetExceededError):
        usage.reserve_vision_call(tenant, 1, call_record=call)
    with factory() as session:
        assert session.get(AICall, (tenant, call["call_id"])) is None
        assert session.scalar(select(VisionDailyUsage.calls_reserved).where(VisionDailyUsage.tenant_id == tenant)) == 1


def test_invalid_audit_rolls_back_allowance(audit_database):
    tenant, factory = audit_database
    call = record("other-tenant")
    with pytest.raises(ValueError, match="tenant"):
        usage.reserve_vision_call(tenant, 2, call_record=call)
    with factory() as session:
        assert session.scalar(select(VisionDailyUsage.calls_reserved).where(VisionDailyUsage.tenant_id == tenant)) is None


def test_audit_completion_is_scoped_to_tenant(audit_database):
    from sqlalchemy.exc import NoResultFound

    tenant, factory = audit_database
    call = record(tenant)
    usage.reserve_vision_call(tenant, 1, call_record=call)
    with pytest.raises(NoResultFound):
        ai_calls.finish_ai_call("another-tenant", call["call_id"], status="completed")
    with factory() as session:
        assert session.get(AICall, (tenant, call["call_id"])).status == "started"
