from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    Post,
    PostContextRecord,
    PostEmbedding,
)
from app.repositories import posts


pytestmark = pytest.mark.integration


@pytest.fixture
def deletion_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(posts, "SessionLocal", factory)

    owner = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"

    try:
        with factory.begin() as session:
            for tenant, post_id in [
                (owner, "shared-post"),
                (other, "shared-post"),
                (owner, "owner-only"),
            ]:
                session.add(Post(
                    tenant_id=tenant,
                    id=post_id,
                    title="Test article",
                    content="Test article content.",
                    required_subject="forest",
                ))

            session.flush()

            for tenant in (owner, other):
                session.add(PostEmbedding(
                    tenant_id=tenant,
                    post_id="shared-post",
                    model="test-model",
                    dimensions=2,
                    task_type="SEMANTIC_SIMILARITY",
                    input_hash="a" * 64,
                    vector=[1.0, 0.0],
                ))
                session.add(PostContextRecord(
                    tenant_id=tenant,
                    post_id="shared-post",
                    input_hash="a" * 64,
                    version="test-version",
                    requirements={},
                    review_status="reviewed",
                ))

        yield SimpleNamespace(
            factory=factory,
            owner=owner,
            other=other,
        )
    finally:
        transaction.rollback()
        connection.close()


def add_job(ctx, status, tenant=None, post_id="shared-post"):
    tenant = tenant or ctx.owner
    job_id = str(uuid4())

    with ctx.factory.begin() as session:
        session.add(EmbeddingJob(
            tenant_id=tenant,
            id=job_id,
            idempotency_key=uuid4().hex,
            model="test-model",
            dimensions=2,
            task_type="SEMANTIC_SIMILARITY",
            status=(
                "running" if status == "processing"
                else "queued" if status == "pending"
                else status
            ),
        ))
        session.flush()

        session.add(EmbeddingJobItem(
            tenant_id=tenant,
            id=str(uuid4()),
            job_id=job_id,
            source_type="post",
            source_id=post_id,
            input_text="Synthetic post snapshot",
            input_hash="a" * 64,
            status=status,
            attempts=0 if status == "pending" else 1,
            max_attempts=3,
            claim_token=(
                str(uuid4()) if status == "processing" else None
            ),
            lease_expires_at=(
                datetime.now(timezone.utc) + timedelta(hours=1)
                if status == "processing"
                else None
            ),
        ))

    return job_id


def test_deletion_cascades_only_within_owner_workspace(deletion_database):
    ctx = deletion_database

    posts.delete_post(ctx.owner, "shared-post")

    with ctx.factory() as session:
        assert session.get(Post, (ctx.owner, "shared-post")) is None

        for tenant in (ctx.owner, ctx.other):
            embedding = session.get(
                PostEmbedding,
                (
                    tenant,
                    "shared-post",
                    "test-model",
                    2,
                    "SEMANTIC_SIMILARITY",
                    "a" * 64,
                ),
            )
            context = session.get(
                PostContextRecord,
                (tenant, "shared-post", "a" * 64, "test-version"),
            )

            if tenant == ctx.owner:
                assert embedding is None
                assert context is None
            else:
                assert embedding is not None
                assert context is not None

        assert session.get(Post, (ctx.other, "shared-post")) is not None
        assert session.get(Post, (ctx.owner, "owner-only")) is not None


def test_missing_post_returns_not_found(deletion_database):
    ctx = deletion_database

    with pytest.raises(posts.PostNotFoundError):
        posts.delete_post(ctx.owner, "missing-post")


def test_other_workspace_cannot_delete_post(deletion_database):
    ctx = deletion_database

    with pytest.raises(posts.PostNotFoundError):
        posts.delete_post(ctx.other, "owner-only")

    assert posts.get_post(ctx.owner, "owner-only").id == "owner-only"


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_active_preparation_blocks_deletion(deletion_database, status):
    ctx = deletion_database
    add_job(ctx, status)

    with pytest.raises(posts.PostBusyError):
        posts.delete_post(ctx.owner, "shared-post")

    assert posts.get_post(ctx.owner, "shared-post").id == "shared-post"


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_preparation_allows_deletion(deletion_database, status):
    ctx = deletion_database
    job_id = add_job(ctx, status)

    posts.delete_post(ctx.owner, "shared-post")

    with pytest.raises(posts.PostNotFoundError):
        posts.get_post(ctx.owner, "shared-post")

    # Historical processing records remain stored.
    with ctx.factory() as session:
        assert session.get(
            EmbeddingJob, (ctx.owner, job_id)
        ) is not None


def test_other_workspaces_job_does_not_block_deletion(deletion_database):
    ctx = deletion_database
    add_job(ctx, "pending", tenant=ctx.other)

    posts.delete_post(ctx.owner, "shared-post")

    assert posts.get_post(ctx.other, "shared-post").id == "shared-post"


def test_another_posts_job_does_not_block_deletion(deletion_database):
    ctx = deletion_database
    add_job(ctx, "pending", post_id="owner-only")

    posts.delete_post(ctx.owner, "shared-post")

    assert posts.get_post(ctx.owner, "owner-only").id == "owner-only"