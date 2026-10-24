from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, Job, JobItem
from app.repositories import jobs as repository


pytestmark = pytest.mark.integration


@pytest.fixture
def processing_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    tenant = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"

    try:
        with factory.begin() as session:
            for owner, image_id, checksum in [
                (tenant, "selected-image", "a" * 64),
                (tenant, "another-image", "b" * 64),
                (other, "other-owner-image", "a" * 64),
            ]:
                session.add(Image(
                    tenant_id=owner,
                    id=image_id,
                    file_path=f"data/images/{image_id}.jpg",
                    checksum=checksum,
                    creator="Test creator",
                    source_url="",
                    license_url="",
                    status="pending",
                ))

        yield SimpleNamespace(
            factory=factory,
            tenant=tenant,
            other=other,
        )
    finally:
        transaction.rollback()
        connection.close()


def read_items(ctx, job_id):
    with ctx.factory() as session:
        return session.scalars(
            select(JobItem).where(
                JobItem.tenant_id == ctx.tenant,
                JobItem.job_id == job_id,
            )
        ).all()


def test_job_contains_only_selected_image(processing_database):
    ctx = processing_database

    job_id = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )
    items = read_items(ctx, job_id)

    assert len(items) == 1
    assert items[0].image_id == "selected-image"
    assert items[0].status == "pending"
    assert items[0].attempts == 0
    assert items[0].max_attempts == 3

    with ctx.factory() as session:
        job = session.get(Job, (ctx.tenant, job_id))
        assert job.status == "queued"


def test_repeated_request_reuses_job(processing_database):
    ctx = processing_database

    first = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )
    original_item_id = read_items(ctx, first)[0].id

    second = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )

    assert second == first
    items = read_items(ctx, second)
    assert len(items) == 1
    assert items[0].id == original_item_id


def test_missing_image_creates_no_job(processing_database):
    ctx = processing_database

    with pytest.raises(repository.ProcessingImageNotFoundError):
        repository.create_image_processing_job(
            ctx.tenant, "missing-image"
        )

    with ctx.factory() as session:
        assert session.scalars(
            select(Job).where(Job.tenant_id == ctx.tenant)
        ).all() == []


def test_other_workspace_image_cannot_be_queued(processing_database):
    ctx = processing_database

    with pytest.raises(repository.ProcessingImageNotFoundError):
        repository.create_image_processing_job(
            ctx.tenant, "other-owner-image"
        )

    with ctx.factory() as session:
        assert session.scalars(
            select(Job).where(Job.tenant_id == ctx.tenant)
        ).all() == []

        image = session.get(
            Image, (ctx.other, "other-owner-image")
        )
        assert image.status == "pending"


@pytest.mark.parametrize(
    "status", ["completed", "needs_review", "failed"]
)
def test_nonpending_image_cannot_start_new_job(
    processing_database, status
):
    ctx = processing_database

    with ctx.factory.begin() as session:
        image = session.get(
            Image, (ctx.tenant, "selected-image")
        )
        image.status = status

    with pytest.raises(repository.ImageNotProcessableError):
        repository.create_image_processing_job(
            ctx.tenant, "selected-image"
        )

    with ctx.factory() as session:
        assert session.scalars(
            select(Job).where(Job.tenant_id == ctx.tenant)
        ).all() == []


def test_existing_bulk_job_is_reused(processing_database):
    ctx = processing_database

    bulk_job = repository.create_processing_job(
        ctx.tenant, "existing-bulk-job"
    )
    original_ids = {item.id for item in read_items(ctx, bulk_job)}
    assert len(original_ids) == 2

    selected_job = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )

    assert selected_job == bulk_job
    assert {
        item.id for item in read_items(ctx, bulk_job)
    } == original_ids


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_job_is_returned_without_reset(
    processing_database, status
):
    ctx = processing_database

    first = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )
    item_id = read_items(ctx, first)[0].id

    with ctx.factory.begin() as session:
        job = session.get(Job, (ctx.tenant, first))
        job.status = status

        item = session.get(JobItem, (ctx.tenant, item_id))
        item.status = status
        item.attempts = 1

        image = session.get(
            Image, (ctx.tenant, "selected-image")
        )
        image.status = status

    repeated = repository.create_image_processing_job(
        ctx.tenant, "selected-image"
    )

    assert repeated == first
    item = read_items(ctx, repeated)[0]
    assert item.status == status
    assert item.attempts == 1