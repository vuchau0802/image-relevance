from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    Image,
    Job,
    JobItem,
    Workspace,
)
from app.repositories import worker_queue as repository


pytestmark = pytest.mark.integration


@pytest.fixture
def queue_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    try:
        yield SimpleNamespace(factory=factory)
    finally:
        transaction.rollback()
        connection.close()


def add_job(
    ctx,
    kind,
    *,
    registered=True,
    job_status="queued",
    item_status="pending",
    available_at=None,
    lease_expires_at=None,
    created_at=None,
):
    now = datetime.now(timezone.utc)
    tenant = f"ws_{uuid4().hex}"
    job_id = str(uuid4())
    source_id = f"img_{uuid4().hex}"

    with ctx.factory.begin() as session:
        if registered:
            session.add(Workspace(
                id=tenant,
                auth_issuer="https://queue-test.clerk.accounts.dev",
                auth_user_id=f"user_{uuid4().hex}",
            ))
            session.flush()

        job_values = {
            "tenant_id": tenant,
            "id": job_id,
            "idempotency_key": uuid4().hex,
            "status": job_status,
            "created_at": created_at or now,
        }

        if kind == "embedding":
            job_values.update(
                model="test-model",
                dimensions=2,
                task_type="SEMANTIC_SIMILARITY",
            )
            job_model = EmbeddingJob
            item_model = EmbeddingJobItem
        else:
            job_model = Job
            item_model = JobItem
            session.add(Image(
                tenant_id=tenant,
                id=source_id,
                file_path="data/images/synthetic.jpg",
                checksum=uuid4().hex * 2,
                creator="Test fixture",
                source_url="",
                license_url="",
                status="pending",
            ))

        session.add(job_model(**job_values))
        session.flush()

        item_values = {
            "tenant_id": tenant,
            "id": str(uuid4()),
            "job_id": job_id,
            "status": item_status,
            "attempts": 1 if item_status == "processing" else 0,
            "max_attempts": 3,
            "available_at": (
                available_at or now - timedelta(minutes=1)
            ),
        }

        if item_status == "processing":
            item_values.update(
                claim_token=str(uuid4()),
                lease_expires_at=lease_expires_at,
            )

        if kind == "embedding":
            item_values.update(
                source_type="image",
                source_id=source_id,
                input_text="Synthetic image description",
                input_hash="a" * 64,
            )
        else:
            item_values["image_id"] = source_id

        session.add(item_model(**item_values))

    return repository.ReadyWorkspaceJob(
        kind=kind,
        tenant_id=tenant,
        job_id=job_id,
    )


def test_discovers_vision_and_embedding_jobs(queue_database):
    ctx = queue_database
    vision = add_job(ctx, "vision")
    embedding = add_job(ctx, "embedding")

    found = repository.list_ready_workspace_jobs()

    assert vision in found
    assert embedding in found


@pytest.mark.parametrize("kind", ["vision", "embedding"])
def test_future_retry_is_not_ready(queue_database, kind):
    candidate = add_job(
        queue_database,
        kind,
        available_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert candidate not in repository.list_ready_workspace_jobs()


@pytest.mark.parametrize("kind", ["vision", "embedding"])
@pytest.mark.parametrize("expired", [False, True])
def test_processing_job_is_ready_only_after_lease_expiry(
    queue_database, kind, expired
):
    lease = datetime.now(timezone.utc) + timedelta(
        hours=-1 if expired else 1
    )
    candidate = add_job(
        queue_database,
        kind,
        job_status="running",
        item_status="processing",
        lease_expires_at=lease,
    )

    found = repository.list_ready_workspace_jobs()
    assert (candidate in found) is expired


def test_terminal_jobs_are_excluded(queue_database):
    candidates = [
        add_job(queue_database, kind, job_status=status)
        for kind in ["vision", "embedding"]
        for status in [
            "completed",
            "completed_with_errors",
            "failed",
        ]
    ]

    found = repository.list_ready_workspace_jobs()
    assert all(candidate not in found for candidate in candidates)


def test_jobs_without_registered_workspace_are_excluded(queue_database):
    candidates = [
        add_job(queue_database, kind, registered=False)
        for kind in ["vision", "embedding"]
    ]

    found = repository.list_ready_workspace_jobs()
    assert all(candidate not in found for candidate in candidates)


def test_limit_applies_across_both_job_types(queue_database):
    now = datetime.now(timezone.utc)

    oldest = add_job(
        queue_database,
        "embedding",
        created_at=now - timedelta(days=3),
    )
    second = add_job(
        queue_database,
        "vision",
        created_at=now - timedelta(days=2),
    )
    add_job(
        queue_database,
        "embedding",
        created_at=now - timedelta(days=1),
    )

    assert repository.list_ready_workspace_jobs(limit=2) == [
        oldest,
        second,
    ]


@pytest.mark.parametrize("limit", [0, 1001, True, 1.5, "20"])
def test_invalid_limits_are_rejected(queue_database, limit):
    with pytest.raises(ValueError, match="limit"):
        repository.list_ready_workspace_jobs(limit=limit)

def test_excluded_oldest_job_does_not_hide_newer_work(queue_database):
    now = datetime.now(timezone.utc)

    oldest = add_job(
        queue_database,
        "vision",
        created_at=now - timedelta(days=2),
    )
    newer = add_job(
        queue_database,
        "embedding",
        created_at=now - timedelta(days=1),
    )

    assert repository.list_ready_workspace_jobs(
        limit=1,
        exclude={oldest},
    ) == [newer]


@pytest.mark.parametrize("different_field", ["kind", "tenant"])
def test_exclusion_matches_job_kind_and_workspace(
    queue_database, different_field
):
    candidate = add_job(queue_database, "vision")

    exclusion = repository.ReadyWorkspaceJob(
        kind="embedding" if different_field == "kind" else "vision",
        tenant_id=(
            f"ws_{uuid4().hex}"
            if different_field == "tenant"
            else candidate.tenant_id
        ),
        job_id=candidate.job_id,
    )

    assert candidate in repository.list_ready_workspace_jobs(
        exclude={exclusion}
    )