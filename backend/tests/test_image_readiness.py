from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, ImageEmbedding, ImageMetadataRecord
from app.repositories import image_readiness, images
from app.schemas.image import ImageMetadata
from app.services.embedding_text import EMBEDDING_TASK_TYPE, prepare_image_input


pytestmark = pytest.mark.integration


@pytest.fixture
def readiness_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(images, "SessionLocal", factory)
    settings = SimpleNamespace(
        embedding_model="readiness-test-model",
        embedding_dimensions=2,
    )
    monkeypatch.setattr(image_readiness, "get_settings", lambda: settings)
    owner = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"
    metadata = ImageMetadata(
        subject="forest",
        category="landscape",
        attributes=["green ferns"],
        caption="A path through a green forest.",
        confidence=0.95,
    )

    try:
        with factory.begin() as session:
            for tenant in (owner, other):
                session.add(Image(
                    tenant_id=tenant,
                    id="shared-image",
                    file_path="data/images/test.jpg",
                    checksum="a" * 64,
                    creator="Test creator",
                    source_url="",
                    license_url="",
                    status="completed",
                ))
            session.flush()
            for tenant in (owner, other):
                session.add(ImageMetadataRecord(
                    tenant_id=tenant,
                    image_id="shared-image",
                    vision_model="test-vision",
                    **metadata.model_dump(),
                ))

        yield SimpleNamespace(
            factory=factory,
            connection=connection,
            owner=owner,
            other=other,
            settings=settings,
            metadata=metadata,
            input_hash=prepare_image_input(metadata).input_hash,
        )
    finally:
        transaction.rollback()
        connection.close()


def save_embedding(ctx, tenant=None, **overrides):
    values = dict(
        tenant_id=tenant or ctx.owner,
        image_id="shared-image",
        model=ctx.settings.embedding_model,
        dimensions=ctx.settings.embedding_dimensions,
        task_type=EMBEDDING_TASK_TYPE,
        input_hash=ctx.input_hash,
        vector=[1.0, 0.0],
    )
    values.update(overrides)
    with ctx.factory.begin() as session:
        session.add(ImageEmbedding(**values))


def listed_image(ctx):
    return images.list_images(ctx.owner).items[0]


def test_completed_analysis_without_embedding_is_not_ready(readiness_database):
    result = listed_image(readiness_database)
    assert result.status == "completed"
    assert result.embedding_ready is False


def test_current_valid_embedding_is_ready(readiness_database):
    ctx = readiness_database
    save_embedding(ctx)
    assert listed_image(ctx).embedding_ready is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "old-model"},
        {"dimensions": 3, "vector": [1.0, 0.0, 0.0]},
        {"task_type": "RETRIEVAL_DOCUMENT"},
        {"input_hash": "b" * 64},
    ],
)
def test_stale_or_different_configuration_is_not_ready(
    readiness_database, overrides
):
    ctx = readiness_database
    save_embedding(ctx, **overrides)
    assert listed_image(ctx).embedding_ready is False


def test_other_workspace_embedding_cannot_make_image_ready(readiness_database):
    ctx = readiness_database
    save_embedding(ctx, tenant=ctx.other)
    assert listed_image(ctx).embedding_ready is False


def test_changed_metadata_invalidates_readiness(readiness_database):
    ctx = readiness_database
    save_embedding(ctx)
    with ctx.factory.begin() as session:
        metadata = session.get(ImageMetadataRecord, (ctx.owner, "shared-image"))
        metadata.caption = "A different forest scene after snowfall."
    assert listed_image(ctx).embedding_ready is False


def test_review_required_image_is_not_ready_even_with_cache(readiness_database):
    ctx = readiness_database
    save_embedding(ctx)
    with ctx.factory.begin() as session:
        image = session.get(Image, (ctx.owner, "shared-image"))
        image.status = "needs_review"
    assert listed_image(ctx).embedding_ready is False


def test_zero_vector_is_not_reported_ready(readiness_database):
    ctx = readiness_database
    save_embedding(ctx, vector=[0.0, 0.0])
    assert listed_image(ctx).embedding_ready is False


def test_missing_metadata_is_not_ready(readiness_database):
    ctx = readiness_database
    save_embedding(ctx)
    with ctx.factory.begin() as session:
        session.delete(session.get(
            ImageMetadataRecord, (ctx.owner, "shared-image")
        ))
    assert listed_image(ctx).embedding_ready is False


def test_readiness_queries_are_batched_for_the_page(readiness_database):
    ctx = readiness_database
    with ctx.factory.begin() as session:
        for number in range(6):
            session.add(Image(
                tenant_id=ctx.owner,
                id=f"extra-{number}",
                file_path="data/images/test.jpg",
                checksum=uuid4().hex * 2,
                creator="Test creator",
                source_url="",
                license_url="",
                status="completed",
            ))
        session.flush()
        for number in range(6):
            session.add(ImageMetadataRecord(
                tenant_id=ctx.owner,
                image_id=f"extra-{number}",
                vision_model="test-vision",
                **ctx.metadata.model_dump(),
            ))

    statements = []

    def record_select(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(ctx.connection, "before_cursor_execute", record_select)
    try:
        result = images.list_images(ctx.owner)
    finally:
        event.remove(ctx.connection, "before_cursor_execute", record_select)

    assert len(result.items) == 7
    assert len(statements) <= 3
