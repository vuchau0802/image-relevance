from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, ImageContextRecord
from app.repositories import context as repository
from app.schemas.context import SceneEvidence


pytestmark = pytest.mark.integration


def scene_fact(feature="snow", state="absent"):
    return SceneEvidence(
        feature=feature,
        state=state,
        source="manual_review",
        explanation="Synthetic evidence for a database test.",
    )


@pytest.fixture
def image_context_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(
        repository, "SessionLocal", factory
    )

    tenants = [f"test-{uuid4()}", f"test-{uuid4()}"]

    try:
        with factory.begin() as session:
            for tenant in tenants:
                session.add(Image(
                    tenant_id=tenant,
                    id="shared-image",
                    file_path="data/images/test.jpg",
                    checksum="a" * 64,
                    source_url="https://example.com/image",
                    creator="Test fixture",
                    license_url="https://example.com/license",
                    status="completed",
                ))

        yield SimpleNamespace(
            factory=factory,
            tenants=tenants,
            image_id="shared-image",
            checksum="a" * 64,
        )

    finally:
        transaction.rollback()
        connection.close()


def save_context(ctx, **changes):
    arguments = {
        "tenant_id": ctx.tenants[0],
        "image_id": ctx.image_id,
        "image_checksum": ctx.checksum,
        "version": "manual-v1",
        "facts": [scene_fact()],
        "reviewed": True,
    }
    arguments.update(changes)
    return repository.save_image_context(**arguments)


def read_context(ctx, **changes):
    arguments = {
        "tenant_id": ctx.tenants[0],
        "image_id": ctx.image_id,
        "version": "manual-v1",
    }
    arguments.update(changes)
    return repository.get_current_image_context(**arguments)


def test_reviewed_image_evidence_round_trip(
    image_context_database,
):
    ctx = image_context_database

    assert save_context(ctx) is True
    assert read_context(ctx) == [scene_fact()]


def test_missing_and_reviewed_empty_evidence_are_distinct(
    image_context_database,
):
    ctx = image_context_database

    assert read_context(ctx) is None

    save_context(ctx, facts=[])

    assert read_context(ctx) == []


def test_review_change_requires_new_version(
    image_context_database,
):
    ctx = image_context_database
    save_context(ctx, reviewed=False)

    assert read_context(ctx) is None

    with pytest.raises(ValueError, match="new version"):
        save_context(ctx, reviewed=True)

    save_context(ctx, version="manual-v2", reviewed=True)

    assert read_context(ctx) is None
    assert read_context(
        ctx, version="manual-v2"
    ) == [scene_fact()]


def test_fact_order_does_not_create_a_different_record(
    image_context_database,
):
    ctx = image_context_database
    facts = [
        scene_fact("snow", "absent"),
        scene_fact("rider", "present"),
    ]

    assert save_context(ctx, facts=facts) is True
    assert save_context(
        ctx, facts=list(reversed(facts))
    ) is False

    assert [
        fact.feature for fact in read_context(ctx)
    ] == ["rider", "snow"]


def test_duplicate_features_are_rejected(
    image_context_database,
):
    ctx = image_context_database

    with pytest.raises(ValueError, match="Duplicate"):
        save_context(ctx, facts=[
            scene_fact("snow", "present"),
            scene_fact("snow", "absent"),
        ])

    assert read_context(ctx) is None


def test_changed_facts_require_new_version(
    image_context_database,
):
    ctx = image_context_database
    save_context(ctx)

    with pytest.raises(ValueError, match="new version"):
        save_context(
            ctx,
            facts=[scene_fact(state="present")],
        )

    assert read_context(ctx) == [scene_fact()]

    save_context(
        ctx,
        version="manual-v2",
        facts=[scene_fact(state="present")],
    )

    assert read_context(
        ctx, version="manual-v2"
    )[0].state == "present"


def test_changed_registered_checksum_invalidates_evidence(
    image_context_database,
):
    ctx = image_context_database
    save_context(ctx)

    with ctx.factory.begin() as session:
        image = session.get(
            Image,
            (ctx.tenants[0], ctx.image_id),
        )
        image.checksum = "b" * 64

    assert read_context(ctx) is None

    with pytest.raises(ValueError, match="checksum differs"):
        save_context(ctx, version="manual-v2")

    with ctx.factory() as session:
        historical = session.get(
            ImageContextRecord,
            (
                ctx.tenants[0],
                ctx.image_id,
                ctx.checksum,
                "manual-v1",
            ),
        )
        assert historical is not None


def test_image_evidence_is_isolated_by_tenant(
    image_context_database,
):
    ctx = image_context_database
    save_context(ctx)

    assert read_context(
        ctx, tenant_id=ctx.tenants[1]
    ) is None

    save_context(
        ctx,
        tenant_id=ctx.tenants[1],
        facts=[scene_fact(state="present")],
    )

    assert read_context(ctx)[0].state == "absent"
    assert read_context(
        ctx, tenant_id=ctx.tenants[1]
    )[0].state == "present"


def test_invalid_stored_facts_fail_validation(
    image_context_database,
):
    ctx = image_context_database
    save_context(ctx)

    with ctx.factory.begin() as session:
        record = session.get(
            ImageContextRecord,
            (
                ctx.tenants[0],
                ctx.image_id,
                ctx.checksum,
                "manual-v1",
            ),
        )
        record.facts = [{
            "feature": "snow",
            "state": "invalid-state",
            "source": "manual_review",
            "explanation": "Deliberately corrupted test data.",
        }]

    with pytest.raises(ValidationError):
        read_context(ctx)