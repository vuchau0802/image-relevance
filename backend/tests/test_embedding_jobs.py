import hashlib
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    EmbeddingDailyUsage,
    AICall,
    Image,
    ImageMetadataRecord,
    Post,
)
from app.repositories import embedding_jobs as repository, usage as usage_repository
from app.repositories import embeddings as embedding_cache
from app.services import embeddings as embedding_service
from app.workers import embedding_runner as embedding_worker
from app.repositories import ai_calls as audit_repository

pytestmark = pytest.mark.integration


@pytest.fixture
def job_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    settings = SimpleNamespace(
        embedding_model="test-model",
        embedding_dimensions=2,
    )

    monkeypatch.setattr(repository, "SessionLocal", factory)
    monkeypatch.setattr(
        repository, "get_settings", lambda: settings
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
                session.add(Post(
                    tenant_id=tenant,
                    id="shared-post",
                    title="Red foxes",
                    content="A red fox outdoors.",
                    required_subject="red fox",
                ))

            session.flush()

            for tenant in tenants:
                session.add(ImageMetadataRecord(
                    tenant_id=tenant,
                    image_id="shared-image",
                    subject="red fox",
                    category="animal",
                    attributes=["standing outdoors"],
                    caption="A red fox standing outdoors.",
                    confidence=0.99,
                    vision_model="test-vision",
                ))

        yield SimpleNamespace(
            factory=factory,
            tenants=tenants,
            settings=settings,
        )

    finally:
        transaction.rollback()
        connection.close()


def read_items(factory, tenant_id, job_id):
    with factory() as session:
        return session.scalars(
            select(EmbeddingJobItem)
            .where(
                EmbeddingJobItem.tenant_id == tenant_id,
                EmbeddingJobItem.job_id == job_id,
            )
            .order_by(EmbeddingJobItem.source_type)
        ).all()


def test_job_contains_image_and_post_snapshots(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    job_id = repository.create_embedding_job(
        tenant, "initial"
    )
    items = read_items(ctx.factory, tenant, job_id)

    assert len(items) == 2
    assert {
        (item.source_type, item.source_id)
        for item in items
    } == {
        ("image", "shared-image"),
        ("post", "shared-post"),
    }

    for item in items:
        assert item.tenant_id == tenant
        assert item.status == "pending"
        assert item.attempts == 0
        assert item.max_attempts == 3
        assert item.input_text.strip()
        assert item.input_hash == hashlib.sha256(
            item.input_text.encode("utf-8")
        ).hexdigest()

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, job_id))
        assert job.status == "queued"
        assert job.model == "test-model"
        assert job.dimensions == 2
        assert job.task_type == "SEMANTIC_SIMILARITY"


def test_repeated_creation_reuses_job_and_items(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_embedding_job(tenant, "initial")
    original_ids = {
        item.id for item in read_items(
            ctx.factory, tenant, first
        )
    }

    second = repository.create_embedding_job(tenant, "initial")

    assert second == first
    assert {
        item.id for item in read_items(
            ctx.factory, tenant, second
        )
    } == original_ids


def test_changed_post_preserves_old_snapshot(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_embedding_job(tenant, "initial")
    old_post_item = next(
        item for item in read_items(ctx.factory, tenant, first)
        if item.source_type == "post"
    )

    with ctx.factory.begin() as session:
        post = session.get(Post, (tenant, "shared-post"))
        post.content = "A red fox sleeping beneath a tree."

    assert repository.create_embedding_job(
        tenant, "initial"
    ) == first

    unchanged = next(
        item for item in read_items(ctx.factory, tenant, first)
        if item.source_type == "post"
    )
    assert unchanged.input_hash == old_post_item.input_hash
    assert unchanged.input_text == old_post_item.input_text

    second = repository.create_embedding_job(tenant, "updated")
    new_post_item = next(
        item for item in read_items(ctx.factory, tenant, second)
        if item.source_type == "post"
    )

    assert second != first
    assert new_post_item.input_hash != old_post_item.input_hash
    assert "sleeping beneath a tree" in new_post_item.input_text


def test_same_key_is_independent_per_tenant(job_database):
    ctx = job_database
    first_tenant, second_tenant = ctx.tenants

    first = repository.create_embedding_job(
        first_tenant, "initial"
    )
    second = repository.create_embedding_job(
        second_tenant, "initial"
    )

    assert first != second
    assert len(read_items(ctx.factory, first_tenant, first)) == 2
    assert len(read_items(ctx.factory, second_tenant, second)) == 2
    assert read_items(ctx.factory, second_tenant, first) == []
    assert read_items(ctx.factory, first_tenant, second) == []


def test_same_key_rejects_changed_configuration(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    repository.create_embedding_job(tenant, "initial")
    ctx.settings.embedding_model = "another-model"

    with pytest.raises(
        ValueError, match="different embedding configuration"
    ):
        repository.create_embedding_job(tenant, "initial")


def test_empty_corpus_creates_completed_job(job_database):
    ctx = job_database
    tenant = f"test-{uuid4()}"

    job_id = repository.create_embedding_job(tenant, "empty")

    assert read_items(ctx.factory, tenant, job_id) == []

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, job_id))
        assert job.status == "completed"
        assert job.finished_at is not None

def test_claim_persists_ownership_and_input_snapshot(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "claim-test")

    claim = repository.claim_next_embedding_item(tenant, job_id)

    assert claim is not None
    assert claim.tenant_id == tenant
    assert claim.job_id == job_id
    assert claim.attempt == 1
    assert claim.claim_token
    assert claim.key.model == "test-model"
    assert claim.key.dimensions == 2
    assert claim.key.input_hash == claim.prepared.input_hash

    assert claim.prepared.input_hash == hashlib.sha256(
        claim.prepared.text.encode("utf-8")
    ).hexdigest()

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        job = session.get(EmbeddingJob, (tenant, job_id))

        assert item.status == "processing"
        assert item.attempts == 1
        assert item.claim_token == claim.claim_token
        assert item.lease_expires_at is not None
        assert item.lease_expires_at > datetime.now(timezone.utc)
        assert item.input_text == claim.prepared.text
        assert job.status == "running"


def test_claim_does_not_reclaim_processing_items(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "claim-test")

    first = repository.claim_next_embedding_item(tenant, job_id)
    second = repository.claim_next_embedding_item(tenant, job_id)
    third = repository.claim_next_embedding_item(tenant, job_id)

    assert first is not None
    assert second is not None
    assert first.item_id != second.item_id
    assert first.claim_token != second.claim_token
    assert third is None


def test_wrong_tenant_cannot_claim_job(job_database):
    ctx = job_database
    owner, other = ctx.tenants
    job_id = repository.create_embedding_job(owner, "claim-test")

    with pytest.raises(ValueError, match="not found"):
        repository.claim_next_embedding_item(other, job_id)

    items = read_items(ctx.factory, owner, job_id)
    assert all(item.status == "pending" for item in items)
    assert all(item.attempts == 0 for item in items)


def test_future_items_are_not_claimed(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "claim-test")

    with ctx.factory.begin() as session:
        items = session.scalars(
            select(EmbeddingJobItem).where(
                EmbeddingJobItem.tenant_id == tenant,
                EmbeddingJobItem.job_id == job_id,
            )
        ).all()

        for item in items:
            item.available_at = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            )

    claim = repository.claim_next_embedding_item(tenant, job_id)

    assert claim is None
    items = read_items(ctx.factory, tenant, job_id)
    assert all(item.attempts == 0 for item in items)


@pytest.mark.parametrize("lease_seconds", [0, True, 3601])
def test_invalid_claim_lease_is_rejected(
    job_database, lease_seconds
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "claim-test")

    with pytest.raises(ValueError, match="lease_seconds"):
        repository.claim_next_embedding_item(
            tenant,
            job_id,
            lease_seconds=lease_seconds,
        )

def cache_claim(monkeypatch, ctx, claim):
    monkeypatch.setattr(
        embedding_cache,
        "SessionLocal",
        ctx.factory,
    )
    embedding_cache.save_cached_embedding(
        claim.key,
        [1.0, 0.0],
    )


def test_completion_clears_ownership_and_records_cache_hit(
    job_database, monkeypatch
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")

    claim = repository.claim_next_embedding_item(tenant, job_id)
    cache_claim(monkeypatch, ctx, claim)

    repository.complete_embedding_claim(
        claim,
        cache_hit=True,
    )

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        job = session.get(EmbeddingJob, (tenant, job_id))

        assert item.status == "completed"
        assert item.cache_hit is True
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.last_error is None
        assert item.finished_at is not None
        assert item.attempts == 1

        # The fixture's other item is still pending.
        assert job.status == "running"
        assert job.finished_at is None


def test_finishing_all_items_completes_job(
    job_database, monkeypatch
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")

    for _ in range(2):
        claim = repository.claim_next_embedding_item(
            tenant, job_id
        )
        assert claim is not None
        cache_claim(monkeypatch, ctx, claim)
        repository.complete_embedding_claim(
            claim,
            cache_hit=False,
        )

    repository.refresh_embedding_job_status(tenant, job_id)

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, job_id))
        assert job.status == "completed"
        assert job.finished_at is not None

    assert repository.claim_next_embedding_item(
        tenant, job_id
    ) is None


def test_completion_requires_cached_embedding(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    with pytest.raises(ValueError, match="cached embedding"):
        repository.complete_embedding_claim(
            claim,
            cache_hit=False,
        )

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "processing"
        assert item.claim_token == claim.claim_token
        assert item.finished_at is None


def test_duplicate_completion_is_rejected(
    job_database, monkeypatch
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")
    claim = repository.claim_next_embedding_item(tenant, job_id)
    cache_claim(monkeypatch, ctx, claim)

    repository.complete_embedding_claim(claim, cache_hit=True)

    with pytest.raises(repository.StaleEmbeddingClaimError):
        repository.complete_embedding_claim(
            claim,
            cache_hit=True,
        )


def test_expired_claim_cannot_complete(
    job_database, monkeypatch
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")
    claim = repository.claim_next_embedding_item(tenant, job_id)
    cache_claim(monkeypatch, ctx, claim)

    with ctx.factory.begin() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        item.lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

    with pytest.raises(repository.StaleEmbeddingClaimError):
        repository.complete_embedding_claim(
            claim,
            cache_hit=True,
        )


def test_wrong_claim_token_cannot_complete(
    job_database, monkeypatch
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "complete")
    claim = repository.claim_next_embedding_item(tenant, job_id)
    cache_claim(monkeypatch, ctx, claim)

    wrong_claim = replace(
        claim,
        claim_token=str(uuid4()),
    )

    with pytest.raises(repository.StaleEmbeddingClaimError):
        repository.complete_embedding_claim(
            wrong_claim,
            cache_hit=True,
        )

    # The original owner can still complete.
    repository.complete_embedding_claim(
        claim,
        cache_hit=True,
    )

def test_retryable_failure_reschedules_item(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "failure")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    status = repository.fail_embedding_claim(
        claim,
        retryable=True,
        error_type="TimeoutError",
    )

    assert status == "pending"

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.attempts == 1
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.finished_at is None
        assert item.available_at > datetime.now(timezone.utc)
        assert item.last_error == "Processing failed: TimeoutError"


def test_permanent_failure_is_not_retried(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "failure")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    status = repository.fail_embedding_claim(
        claim,
        retryable=False,
        error_type="ValueError",
    )

    assert status == "failed"

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.attempts == 1
        assert item.finished_at is not None
        assert item.claim_token is None
        assert item.lease_expires_at is None


def test_final_attempt_failure_is_terminal(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "failure")

    with ctx.factory.begin() as session:
        items = session.scalars(
            select(EmbeddingJobItem).where(
                EmbeddingJobItem.tenant_id == tenant,
                EmbeddingJobItem.job_id == job_id,
            )
        ).all()
        for item in items:
            item.max_attempts = 1

    claim = repository.claim_next_embedding_item(tenant, job_id)

    assert repository.fail_embedding_claim(
        claim,
        retryable=True,
        error_type="TimeoutError",
    ) == "failed"


def test_expired_lease_is_requeued_once(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "recovery")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    with ctx.factory.begin() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        item.lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

    result = repository.recover_expired_embedding_claims(
        tenant, job_id
    )

    assert result == {"requeued": 1, "failed": 0}

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "pending"
        assert item.attempts == 1
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.available_at > datetime.now(timezone.utc)
        assert item.last_error == (
            "Worker lease expired before completion"
        )

    assert repository.recover_expired_embedding_claims(
        tenant, job_id
    ) == {"requeued": 0, "failed": 0}

    with pytest.raises(repository.StaleEmbeddingClaimError):
        repository.fail_embedding_claim(
            claim,
            retryable=True,
            error_type="TimeoutError",
        )


def test_final_expired_lease_becomes_failed(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "recovery")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    with ctx.factory.begin() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        item.max_attempts = 1
        item.lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

    assert repository.recover_expired_embedding_claims(
        tenant, job_id
    ) == {"requeued": 0, "failed": 1}

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "failed"
        assert item.attempts == 1
        assert item.finished_at is not None
        assert item.claim_token is None
        assert item.lease_expires_at is None


def test_recovery_leaves_live_claim_untouched(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "recovery")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    assert repository.recover_expired_embedding_claims(
        tenant, job_id
    ) == {"requeued": 0, "failed": 0}

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "processing"
        assert item.claim_token == claim.claim_token


def test_all_failed_items_mark_job_failed(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "failure")

    for _ in range(2):
        claim = repository.claim_next_embedding_item(
            tenant, job_id
        )
        assert claim is not None

        repository.fail_embedding_claim(
            claim,
            retryable=False,
            error_type="ValueError",
        )

    summary = repository.get_embedding_job_summary(
        tenant, job_id
    )

    assert summary["status"] == "failed"
    assert summary["failed"] == 2
    assert summary["pending"] == 0
    assert summary["processing"] == 0

def test_unstarted_release_restores_attempt_count(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "release")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    assert claim.attempt == 1

    repository.release_unstarted_embedding_claim(claim)

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "pending"
        assert item.attempts == 0
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.finished_at is None


def test_unstarted_release_preserves_previous_failure(
    job_database,
):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "release")

    original = repository.claim_next_embedding_item(
        tenant, job_id
    )

    repository.fail_embedding_claim(
        original,
        retryable=True,
        error_type="TimeoutError",
    )

    # Make that retry ready, while postponing the other item.
    with ctx.factory.begin() as session:
        items = session.scalars(
            select(EmbeddingJobItem).where(
                EmbeddingJobItem.tenant_id == tenant,
                EmbeddingJobItem.job_id == job_id,
            )
        ).all()

        for item in items:
            if item.id == original.item_id:
                item.available_at = (
                    datetime.now(timezone.utc)
                    - timedelta(seconds=1)
                )
            else:
                item.available_at = (
                    datetime.now(timezone.utc)
                    + timedelta(hours=1)
                )

    retry = repository.claim_next_embedding_item(
        tenant, job_id
    )

    assert retry.item_id == original.item_id
    assert retry.attempt == 2

    repository.release_unstarted_embedding_claim(retry)

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, retry.item_id),
        )
        assert item.status == "pending"
        assert item.attempts == 1
        assert item.last_error == "Processing failed: TimeoutError"
        assert item.claim_token is None
        assert item.lease_expires_at is None


def test_duplicate_unstarted_release_is_rejected(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(tenant, "release")
    claim = repository.claim_next_embedding_item(tenant, job_id)

    repository.release_unstarted_embedding_claim(claim)

    with pytest.raises(repository.StaleEmbeddingClaimError):
        repository.release_unstarted_embedding_claim(claim)

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.attempts == 0

@pytest.fixture
def worker_database(job_database, monkeypatch):
    ctx = job_database
    ctx.settings.embedding_daily_call_limit = 0

    monkeypatch.setattr(
        embedding_cache,
        "SessionLocal",
        ctx.factory,
    )
    monkeypatch.setattr(
        usage_repository,
        "SessionLocal",
        ctx.factory,
    )
    monkeypatch.setattr(
        embedding_service,
        "get_settings",
        lambda: ctx.settings,
    )

    client_factory = Mock(
        side_effect=AssertionError(
            "This test must not construct a Gemini client"
        )
    )
    monkeypatch.setattr(
        embedding_service.genai,
        "Client",
        client_factory,
    )

    ctx.client_factory = client_factory
    return ctx

def assert_no_embedding_call_records(ctx, tenant):
    with ctx.factory() as session:
        calls = session.scalars(
            select(AICall).where(
                AICall.tenant_id == tenant,
            )
        ).all()

        usage = session.scalars(
            select(EmbeddingDailyUsage).where(
                EmbeddingDailyUsage.tenant_id == tenant,
            )
        ).all()

        assert calls == []
        assert usage == []


def test_worker_budget_block_restores_claim_in_database(
    worker_database,
):
    ctx = worker_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(
        tenant, "worker-budget"
    )
    claim = repository.claim_next_embedding_item(
        tenant, job_id
    )

    assert embedding_worker.process_embedding_claim(
        claim
    ) is False

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "pending"
        assert item.attempts == 0
        assert item.claim_token is None
        assert item.lease_expires_at is None
        assert item.finished_at is None

    ctx.client_factory.assert_not_called()
    assert_no_embedding_call_records(ctx, tenant)


def test_worker_cache_hit_completes_with_zero_allowance(
    worker_database,
):
    ctx = worker_database
    tenant = ctx.tenants[0]
    job_id = repository.create_embedding_job(
        tenant, "worker-cache"
    )
    claim = repository.claim_next_embedding_item(
        tenant, job_id
    )

    embedding_cache.save_cached_embedding(
        claim.key,
        [1.0, 0.0],
    )

    assert embedding_worker.process_embedding_claim(
        claim
    ) is True

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "completed"
        assert item.cache_hit is True
        assert item.attempts == 1
        assert item.claim_token is None
        assert item.lease_expires_at is None

    ctx.client_factory.assert_not_called()
    assert_no_embedding_call_records(ctx, tenant)

def test_worker_cache_miss_persists_embedding_and_audit(
    worker_database, monkeypatch
):
    ctx = worker_database
    tenant = ctx.tenants[0]

    ctx.settings.embedding_daily_call_limit = 10
    ctx.settings.gemini_api_key = SimpleNamespace(
        get_secret_value=lambda: "fake-test-key"
    )

    monkeypatch.setattr(
        audit_repository,
        "SessionLocal",
        ctx.factory,
    )

    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[
            SimpleNamespace(values=[3.0, 4.0])
        ]
    )

    ctx.client_factory.side_effect = None
    ctx.client_factory.return_value = client

    job_id = repository.create_embedding_job(
        tenant, "worker-cache-miss"
    )
    claim = repository.claim_next_embedding_item(
        tenant, job_id
    )

    assert embedding_cache.get_cached_embedding(
        claim.key
    ) is None

    assert embedding_worker.process_embedding_claim(
        claim
    ) is True

    assert embedding_cache.get_cached_embedding(
        claim.key
    ) == pytest.approx([0.6, 0.8])

    with ctx.factory() as session:
        item = session.get(
            EmbeddingJobItem,
            (tenant, claim.item_id),
        )
        assert item.status == "completed"
        assert item.cache_hit is False
        assert item.claim_token is None
        assert item.lease_expires_at is None

        call = session.execute(
            select(AICall).where(
                AICall.tenant_id == tenant,
                AICall.job_id == job_id,
            )
        ).scalar_one()

        assert call.status == "completed"
        assert call.operation == "embedding"
        assert call.job_item_id == claim.item_id
        assert call.attempt == 1
        assert call.model == claim.key.model
        assert call.image_id == (
            claim.key.source_id
            if claim.key.source_type == "image"
            else None
        )
        assert call.post_id == (
            claim.key.source_id
            if claim.key.source_type == "post"
            else None
        )
        assert call.finished_at is not None

        usage = session.execute(
            select(EmbeddingDailyUsage).where(
                EmbeddingDailyUsage.tenant_id == tenant,
            )
        ).scalar_one()

        assert usage.calls_reserved == 1

    ctx.client_factory.assert_called_once()
    client.models.embed_content.assert_called_once()
    client.close.assert_called_once()

def test_single_post_job_contains_only_selected_post(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    with ctx.factory.begin() as session:
        session.add(Post(
            tenant_id=tenant,
            id="another-post",
            title="Another article",
            content="Another red fox article.",
            required_subject="red fox",
        ))

    job_id = repository.create_post_embedding_job(
        tenant, "shared-post"
    )
    items = read_items(ctx.factory, tenant, job_id)

    assert len(items) == 1
    item = items[0]
    assert item.source_type == "post"
    assert item.source_id == "shared-post"
    assert item.status == "pending"
    assert item.attempts == 0
    assert item.input_hash == hashlib.sha256(
        item.input_text.encode("utf-8")
    ).hexdigest()

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, job_id))
        assert job.status == "queued"
        assert job.model == ctx.settings.embedding_model
        assert job.dimensions == ctx.settings.embedding_dimensions


def test_single_post_job_reuses_identical_request(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_post_embedding_job(
        tenant, "shared-post"
    )
    second = repository.create_post_embedding_job(
        tenant, "shared-post"
    )

    assert second == first
    assert len(read_items(ctx.factory, tenant, first)) == 1


def test_single_post_job_rejects_other_workspace_post(job_database):
    ctx = job_database
    owner, other = ctx.tenants

    with ctx.factory.begin() as session:
        session.add(Post(
            tenant_id=owner,
            id="owner-only",
            title="Private article",
            content="Private red fox content.",
            required_subject="red fox",
        ))

    with pytest.raises(repository.EmbeddingPostNotFoundError):
        repository.create_post_embedding_job(other, "owner-only")

    with ctx.factory() as session:
        assert session.scalars(
            select(EmbeddingJob).where(
                EmbeddingJob.tenant_id == other
            )
        ).all() == []


def test_single_post_job_rejects_missing_post(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    with pytest.raises(repository.EmbeddingPostNotFoundError):
        repository.create_post_embedding_job(tenant, "missing-post")

    with ctx.factory() as session:
        assert session.scalars(
            select(EmbeddingJob).where(
                EmbeddingJob.tenant_id == tenant
            )
        ).all() == []


def test_single_post_change_creates_new_snapshot(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_post_embedding_job(
        tenant, "shared-post"
    )
    original = read_items(ctx.factory, tenant, first)[0]

    with ctx.factory.begin() as session:
        post = session.get(Post, (tenant, "shared-post"))
        post.content = "Updated article about a fox family."

    second = repository.create_post_embedding_job(
        tenant, "shared-post"
    )
    updated = read_items(ctx.factory, tenant, second)[0]

    assert second != first
    assert updated.input_hash != original.input_hash
    assert "Updated article" in updated.input_text
    assert read_items(
        ctx.factory, tenant, first
    )[0].input_text == original.input_text


@pytest.mark.parametrize(
    "setting,new_value",
    [
        ("embedding_model", "another-test-model"),
        ("embedding_dimensions", 3),
    ],
)
def test_single_post_configuration_change_creates_new_job(
    job_database, setting, new_value
):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_post_embedding_job(
        tenant, "shared-post"
    )

    setattr(ctx.settings, setting, new_value)

    second = repository.create_post_embedding_job(
        tenant, "shared-post"
    )

    assert second != first

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, second))
        assert job.model == ctx.settings.embedding_model
        assert job.dimensions == ctx.settings.embedding_dimensions

def test_single_image_job_contains_only_selected_image(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    job_id = repository.create_image_embedding_job(
        tenant, "shared-image"
    )
    items = read_items(ctx.factory, tenant, job_id)

    assert len(items) == 1
    item = items[0]
    assert item.source_type == "image"
    assert item.source_id == "shared-image"
    assert item.status == "pending"
    assert item.attempts == 0
    assert item.max_attempts == 3
    assert item.input_hash == hashlib.sha256(
        item.input_text.encode("utf-8")
    ).hexdigest()

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, job_id))
        assert job.status == "queued"
        assert job.model == ctx.settings.embedding_model
        assert job.dimensions == ctx.settings.embedding_dimensions


def test_single_image_embedding_request_reuses_job(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_image_embedding_job(
        tenant, "shared-image"
    )
    original_id = read_items(ctx.factory, tenant, first)[0].id

    second = repository.create_image_embedding_job(
        tenant, "shared-image"
    )

    assert second == first
    items = read_items(ctx.factory, tenant, second)
    assert len(items) == 1
    assert items[0].id == original_id


@pytest.mark.parametrize("case", ["missing", "other-owner"])
def test_missing_or_unowned_image_cannot_be_embedded(
    job_database, case
):
    ctx = job_database

    if case == "missing":
        tenant = ctx.tenants[0]
        image_id = "missing-image"
    else:
        tenant = ctx.tenants[1]
        image_id = "shared-image"

        # Keep the first owner's image; remove the second owner's copy.
        with ctx.factory.begin() as session:
            session.delete(
                session.get(Image, (tenant, image_id))
            )

    with pytest.raises(repository.EmbeddingImageNotFoundError):
        repository.create_image_embedding_job(tenant, image_id)

    with ctx.factory() as session:
        assert session.scalars(
            select(EmbeddingJob).where(
                EmbeddingJob.tenant_id == tenant
            )
        ).all() == []


@pytest.mark.parametrize(
    "status",
    ["pending", "processing", "needs_review", "failed"],
)
def test_unfinished_image_analysis_blocks_embedding(
    job_database, status
):
    ctx = job_database
    tenant = ctx.tenants[0]

    with ctx.factory.begin() as session:
        image = session.get(Image, (tenant, "shared-image"))
        image.status = status

    with pytest.raises(repository.EmbeddingImageNotReadyError):
        repository.create_image_embedding_job(
            tenant, "shared-image"
        )

    with ctx.factory() as session:
        assert session.scalars(
            select(EmbeddingJob).where(
                EmbeddingJob.tenant_id == tenant
            )
        ).all() == []


def test_image_without_metadata_cannot_be_embedded(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    with ctx.factory.begin() as session:
        session.delete(
            session.get(
                ImageMetadataRecord,
                (tenant, "shared-image"),
            )
        )

    with pytest.raises(
        repository.EmbeddingImageNotReadyError,
        match="metadata",
    ):
        repository.create_image_embedding_job(
            tenant, "shared-image"
        )

    with ctx.factory() as session:
        assert session.scalars(
            select(EmbeddingJob).where(
                EmbeddingJob.tenant_id == tenant
            )
        ).all() == []


def test_changed_image_metadata_creates_new_snapshot(job_database):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_image_embedding_job(
        tenant, "shared-image"
    )
    original = read_items(ctx.factory, tenant, first)[0]

    with ctx.factory.begin() as session:
        metadata = session.get(
            ImageMetadataRecord,
            (tenant, "shared-image"),
        )
        metadata.caption = "A red fox resting beside a tree."

    second = repository.create_image_embedding_job(
        tenant, "shared-image"
    )
    updated = read_items(ctx.factory, tenant, second)[0]

    assert second != first
    assert updated.input_hash != original.input_hash
    assert "resting beside a tree" in updated.input_text
    assert read_items(
        ctx.factory, tenant, first
    )[0].input_text == original.input_text


@pytest.mark.parametrize(
    "setting,new_value",
    [
        ("embedding_model", "another-test-model"),
        ("embedding_dimensions", 3),
    ],
)
def test_image_embedding_configuration_changes_create_new_job(
    job_database, setting, new_value
):
    ctx = job_database
    tenant = ctx.tenants[0]

    first = repository.create_image_embedding_job(
        tenant, "shared-image"
    )

    setattr(ctx.settings, setting, new_value)

    second = repository.create_image_embedding_job(
        tenant, "shared-image"
    )

    assert second != first

    with ctx.factory() as session:
        job = session.get(EmbeddingJob, (tenant, second))
        assert job.model == ctx.settings.embedding_model
        assert job.dimensions == ctx.settings.embedding_dimensions