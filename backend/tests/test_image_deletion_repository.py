import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    Image,
    ImageEmbedding,
    ImageFileCleanupTask,
    ImageMetadataRecord,
    Job,
    JobItem,
)
from app.repositories import image_deletion as repository


pytestmark = pytest.mark.integration


@pytest.fixture
def deletion_database(monkeypatch, tmp_path):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    owner = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"
    image_id = f"img_{uuid4().hex}"
    private_id = f"img_{uuid4().hex}"
    data = b"Synthetic registered file"
    checksum = hashlib.sha256(data).hexdigest()

    try:
        with factory.begin() as session:
            for tenant, identifier in [
                (owner, image_id),
                (other, image_id),
                (owner, private_id),
            ]:
                content = data if identifier == image_id else data + b"other"
                relative = f"data/uploads/{tenant}/{identifier}.jpg"
                path = tmp_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

                session.add(Image(
                    tenant_id=tenant,
                    id=identifier,
                    file_path=relative,
                    checksum=hashlib.sha256(content).hexdigest(),
                    creator="Test creator",
                    source_url="",
                    license_url="",
                    status="completed",
                ))

            session.flush()

            for tenant in (owner, other):
                session.add(ImageMetadataRecord(
                    tenant_id=tenant,
                    image_id=image_id,
                    subject="forest",
                    category="landscape",
                    attributes=["green trees"],
                    caption="A green forest.",
                    confidence=0.95,
                    vision_model="test-vision",
                ))
                session.add(ImageEmbedding(
                    tenant_id=tenant,
                    image_id=image_id,
                    model="test-model",
                    dimensions=2,
                    task_type="SEMANTIC_SIMILARITY",
                    input_hash="a" * 64,
                    vector=[1.0, 0.0],
                ))

        yield SimpleNamespace(
            factory=factory,
            owner=owner,
            other=other,
            image_id=image_id,
            private_id=private_id,
            checksum=checksum,
            relative=f"data/uploads/{owner}/{image_id}.jpg",
            path=tmp_path / f"data/uploads/{owner}/{image_id}.jpg",
        )
    finally:
        transaction.rollback()
        connection.close()


def add_job(ctx, kind, status):
    job_id = str(uuid4())
    item_id = str(uuid4())
    job_status = (
        "running" if status == "processing"
        else "queued" if status == "pending"
        else "completed" if status == "needs_review"
        else status
    )

    with ctx.factory.begin() as session:
        common = {
            "tenant_id": ctx.owner,
            "id": job_id,
            "idempotency_key": uuid4().hex,
            "status": job_status,
        }
        if kind == "vision":
            session.add(Job(**common))
        else:
            session.add(EmbeddingJob(
                **common,
                model="test-model",
                dimensions=2,
                task_type="SEMANTIC_SIMILARITY",
            ))
        session.flush()

        values = {
            "tenant_id": ctx.owner,
            "id": item_id,
            "job_id": job_id,
            "status": status,
            "attempts": 0 if status == "pending" else 1,
            "max_attempts": 3,
            "claim_token": (
                str(uuid4()) if status == "processing" else None
            ),
            "lease_expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
                if status == "processing" else None
            ),
        }
        if kind == "vision":
            session.add(JobItem(
                **values,
                image_id=ctx.image_id,
            ))
        else:
            session.add(EmbeddingJobItem(
                **values,
                source_type="image",
                source_id=ctx.image_id,
                input_text="Synthetic image snapshot",
                input_hash="a" * 64,
            ))

    return job_id, item_id


def test_deletion_queues_cleanup_without_removing_file(deletion_database):
    ctx = deletion_database

    cleanup_id = repository.delete_image(ctx.owner, ctx.image_id)

    with ctx.factory() as session:
        assert session.get(Image, (ctx.owner, ctx.image_id)) is None
        assert session.get(
            ImageMetadataRecord, (ctx.owner, ctx.image_id)
        ) is None
        assert session.scalars(
            select(ImageEmbedding).where(
                ImageEmbedding.tenant_id == ctx.owner,
                ImageEmbedding.image_id == ctx.image_id,
            )
        ).all() == []

        task = session.get(ImageFileCleanupTask, (ctx.owner, cleanup_id))
        assert task.image_id == ctx.image_id
        assert task.file_path == ctx.relative
        assert task.checksum == ctx.checksum
        assert task.status == "pending"
        assert task.attempts == 0

        assert session.get(Image, (ctx.other, ctx.image_id)) is not None
        assert session.get(
            ImageMetadataRecord, (ctx.other, ctx.image_id)
        ) is not None

    assert ctx.path.is_file()


@pytest.mark.parametrize("case", ["missing", "unowned"])
def test_missing_or_unowned_image_is_not_deleted(deletion_database, case):
    ctx = deletion_database
    tenant = ctx.owner if case == "missing" else ctx.other
    identifier = f"img_{uuid4().hex}" if case == "missing" else ctx.private_id

    with pytest.raises(repository.ImageNotFoundError):
        repository.delete_image(tenant, identifier)

    with ctx.factory() as session:
        assert session.get(Image, (ctx.owner, ctx.private_id)) is not None


@pytest.mark.parametrize("kind", ["vision", "embedding"])
@pytest.mark.parametrize("status", ["pending", "processing"])
def test_active_processing_blocks_deletion(deletion_database, kind, status):
    ctx = deletion_database
    add_job(ctx, kind, status)

    with pytest.raises(repository.ImageBusyError):
        repository.delete_image(ctx.owner, ctx.image_id)

    with ctx.factory() as session:
        assert session.get(Image, (ctx.owner, ctx.image_id)) is not None
        assert session.scalars(
            select(ImageFileCleanupTask).where(
                ImageFileCleanupTask.tenant_id == ctx.owner
            )
        ).all() == []
    assert ctx.path.is_file()


@pytest.mark.parametrize("status", ["completed", "needs_review", "failed"])
def test_finished_vision_items_are_removed_before_image(
    deletion_database, status
):
    ctx = deletion_database
    job_id, item_id = add_job(ctx, "vision", status)

    repository.delete_image(ctx.owner, ctx.image_id)

    with ctx.factory() as session:
        assert session.get(JobItem, (ctx.owner, item_id)) is None
        assert session.get(Image, (ctx.owner, ctx.image_id)) is None
        assert session.get(Job, (ctx.owner, job_id)).status == "completed"


def test_cleanup_insert_failure_rolls_back_deletion(deletion_database):
    ctx = deletion_database
    _, item_id = add_job(ctx, "vision", "completed")

    with ctx.factory.begin() as session:
        session.add(ImageFileCleanupTask(
            tenant_id=ctx.owner,
            image_id=ctx.image_id,
            file_path=ctx.relative,
            checksum=ctx.checksum,
        ))

    with pytest.raises(IntegrityError):
        repository.delete_image(ctx.owner, ctx.image_id)

    with ctx.factory() as session:
        assert session.get(Image, (ctx.owner, ctx.image_id)) is not None
        assert session.get(JobItem, (ctx.owner, item_id)) is not None
    assert ctx.path.is_file()


def test_corpus_file_cannot_be_queued_for_deletion(deletion_database):
    ctx = deletion_database

    with ctx.factory.begin() as session:
        image = session.get(Image, (ctx.owner, ctx.image_id))
        image.file_path = "data/images/img_001.jpg"

    with pytest.raises(repository.ImageDeletionNotAllowedError):
        repository.delete_image(ctx.owner, ctx.image_id)

    with ctx.factory() as session:
        assert session.get(Image, (ctx.owner, ctx.image_id)) is not None
        assert session.scalars(
            select(ImageFileCleanupTask).where(
                ImageFileCleanupTask.tenant_id == ctx.owner
            )
        ).all() == []