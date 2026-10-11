from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import app.repositories.jobs as jobs
from app.database import engine
from app.models import Image, ImageMetadataRecord, Job, JobItem
from app.schemas.image import ImageMetadata
from app.services.classification import assess_classification


@pytest.fixture
def temporary_job(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    monkeypatch.setattr(jobs, "SessionLocal", factory)

    tenant_id = f"test-{uuid4()}"
    job_id = str(uuid4())
    item_id = str(uuid4())

    try:
        with factory.begin() as session:
            session.add(Image(
                tenant_id=tenant_id,
                id="test_image",
                file_path="data/images/test_image.jpg",
                checksum="a" * 64,
                source_url="https://example.com/image",
                creator="Test fixture",
                license_url="https://example.com/license",
                status="pending",
            ))
            session.add(Job(
                tenant_id=tenant_id,
                id=job_id,
                idempotency_key="test-job",
                status="queued",
            ))
            session.flush()

            session.add(JobItem(
                tenant_id=tenant_id,
                id=item_id,
                job_id=job_id,
                image_id="test_image",
                status="pending",
                attempts=0,
                max_attempts=3,
            ))

        yield tenant_id, job_id, item_id, factory

    finally:
        transaction.rollback()
        connection.close()


def expire_lease(tenant_id, item_id, factory):
    with factory.begin() as session:
        item = session.get(JobItem, (tenant_id, item_id))
        item.lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )


def sample_result():
    metadata = ImageMetadata(
        subject="red fox",
        category="animal",
        attributes=["reddish fur"],
        caption="A red fox outdoors",
        confidence=0.90,
    )
    return assess_classification(metadata, min_confidence=0.70)


def test_expired_lease_is_requeued_and_old_claim_rejected(
    temporary_job,
):
    tenant, job_id, item_id, factory = temporary_job

    claimed = jobs.claim_next_item(tenant, job_id)
    assert claimed is not None
    assert claimed.attempt == 1

    expire_lease(tenant, item_id, factory)

    recovery = jobs.recover_expired_claims(tenant, job_id)
    assert recovery == {"requeued": 1, "failed": 0}

    with factory() as session:
        item = session.get(JobItem, (tenant, item_id))
        image = session.get(Image, (tenant, "test_image"))

        assert item.status == "pending"
        assert item.attempts == 1
        assert item.claim_token is None
        assert item.available_at > datetime.now(timezone.utc)
        assert image.status == "pending"

    with pytest.raises(jobs.StaleClaimError):
        jobs.complete_claim(claimed, sample_result(), "test-model")


def test_expired_final_attempt_is_failed(temporary_job):
    tenant, job_id, item_id, factory = temporary_job

    with factory.begin() as session:
        item = session.get(JobItem, (tenant, item_id))
        item.max_attempts = 1

    jobs.claim_next_item(tenant, job_id)
    expire_lease(tenant, item_id, factory)

    recovery = jobs.recover_expired_claims(tenant, job_id)
    assert recovery == {"requeued": 0, "failed": 1}

    with factory() as session:
        item = session.get(JobItem, (tenant, item_id))
        image = session.get(Image, (tenant, "test_image"))
        job = session.get(Job, (tenant, job_id))

        assert item.status == "failed"
        assert item.attempts == 1
        assert image.status == "failed"
        assert job.status == "failed"


def test_completion_saves_one_result_and_finishes_job(
    temporary_job,
):
    tenant, job_id, item_id, factory = temporary_job

    claimed = jobs.claim_next_item(tenant, job_id)
    jobs.complete_claim(claimed, sample_result(), "test-model")

    with factory() as session:
        item = session.get(JobItem, (tenant, item_id))
        image = session.get(Image, (tenant, "test_image"))
        job = session.get(Job, (tenant, job_id))

        assert item.status == "completed"
        assert image.status == "completed"
        assert job.status == "completed"

        count = session.execute(
            select(func.count())
            .select_from(ImageMetadataRecord)
            .where(ImageMetadataRecord.tenant_id == tenant)
        ).scalar_one()

        assert count == 1

    with pytest.raises(jobs.StaleClaimError):
        jobs.complete_claim(claimed, sample_result(), "test-model")


def test_other_tenant_cannot_claim_job(temporary_job):
    _, job_id, _, _ = temporary_job

    with pytest.raises(ValueError, match="Job not found"):
        jobs.claim_next_item("different-tenant", job_id)