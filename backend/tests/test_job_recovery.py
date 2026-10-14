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

def test_worker_budget_block_preserves_attempt_history(
    temporary_job,
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from PIL import Image as PillowImage
    from pydantic import SecretStr

    from app.services import vision
    from app.workers import runner

    tenant, job_id, item_id, factory = temporary_job

    # Simulate one previous actual failure.
    with factory.begin() as session:
        item = session.get(JobItem, (tenant, item_id))
        item.attempts = 1
        item.last_error = "Processing failed: APITimeoutError"

    claimed = jobs.claim_next_item(
        tenant,
        job_id,
        lease_seconds=1200,
    )
    assert claimed.attempt == 2

    image_path = tmp_path / "test_image.jpg"
    PillowImage.new("RGB", (16, 16)).save(image_path)

    settings = SimpleNamespace(
        gemini_api_key=SecretStr("unused-test-key"),
        vision_model="test-model",
        min_classification_confidence=0.70,
        vision_daily_call_limit=0,
    )

    client = MagicMock()
    client.interactions.create.side_effect = AssertionError(
        "A budget block must not contact Gemini"
    )

    # Use a local test image and fake client. Keep real budget checking
    # and database claim release active.
    monkeypatch.setattr(runner, "verify_file", lambda claim: image_path)
    monkeypatch.setattr(vision, "get_settings", lambda: settings)
    monkeypatch.setattr(vision, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        vision.genai,
        "Client",
        lambda **kwargs: client,
    )

    assert runner.process_claim(claimed, settings) is False

    client.interactions.create.assert_not_called()
    client.close.assert_called_once()
    assert not (tmp_path / "data" / "ai_calls.jsonl").exists()

    with factory() as session:
        item = session.get(JobItem, (tenant, item_id))
        image = session.get(Image, (tenant, "test_image"))
        job = session.get(Job, (tenant, job_id))

        assert item.status == "pending"
        assert item.attempts == 1
        assert item.last_error == "Processing failed: APITimeoutError"
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.finished_at is None
        assert image.status == "pending"
        assert job.status == "running"

        metadata_count = session.scalar(
            select(func.count())
            .select_from(ImageMetadataRecord)
            .where(ImageMetadataRecord.tenant_id == tenant)
        )
        assert metadata_count == 0

def test_reprocessing_preserves_failed_history_and_is_idempotent(
    temporary_job,
):
    tenant, old_job_id, old_item_id, factory = temporary_job
    previous_error = "Processing failed: APITimeoutError"

    with factory.begin() as session:
        image = session.get(Image, (tenant, "test_image"))
        old_item = session.get(JobItem, (tenant, old_item_id))
        old_job = session.get(Job, (tenant, old_job_id))
        image.status = "failed"
        old_item.status = "failed"
        old_item.attempts = 3
        old_item.last_error = previous_error
        old_item.finished_at = datetime.now(timezone.utc)
        old_job.status = "failed"
        old_job.finished_at = old_item.finished_at

    new_job_id = jobs.create_processing_job(
        tenant,
        "failed-reprocessing-test",
        source_status="failed",
    )
    assert new_job_id != old_job_id
    assert jobs.create_processing_job(
        tenant,
        "failed-reprocessing-test",
        source_status="failed",
    ) == new_job_id

    summary = jobs.get_job_summary(tenant, new_job_id)
    assert summary["status"] == "queued"
    assert summary["total"] == 1
    assert summary["pending"] == 1

    with factory() as session:
        old_item = session.get(JobItem, (tenant, old_item_id))
        old_job = session.get(Job, (tenant, old_job_id))
        image = session.get(Image, (tenant, "test_image"))
        new_items = session.scalars(
            select(JobItem).where(
                JobItem.tenant_id == tenant,
                JobItem.job_id == new_job_id,
            )
        ).all()
        assert len(new_items) == 1
        assert new_items[0].status == "pending"
        assert new_items[0].attempts == 0
        assert new_items[0].max_attempts == 3
        assert new_items[0].image_id == "test_image"
        assert image.status == "pending"
        assert old_item.status == "failed"
        assert old_item.attempts == 3
        assert old_item.last_error == previous_error
        assert old_item.finished_at is not None
        assert old_job.status == "failed"
        assert old_job.finished_at is not None


def test_job_creation_rejects_invalid_source_status(temporary_job):
    tenant, _, _, factory = temporary_job

    with pytest.raises(ValueError, match="source_status"):
        jobs.create_processing_job(
            tenant,
            "invalid-source-test",
            source_status="completed",
        )

    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.tenant_id == tenant)
        )
        assert count == 1

