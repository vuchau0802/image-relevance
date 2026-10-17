from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import EmbeddingJob, EmbeddingJobItem
from app.repositories import embedding_jobs as repository
from app.services.embedding_text import prepare_input


pytestmark = pytest.mark.integration


def test_concurrent_claims_assign_each_item_once(monkeypatch):
    # Each repository transaction obtains its own connection.
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(
        repository,
        "SessionLocal",
        factory,
    )

    tenant = f"test-{uuid4()}"
    job_id = str(uuid4())
    barrier = Barrier(4)

    try:
        with factory.begin() as session:
            session.add(EmbeddingJob(
                tenant_id=tenant,
                id=job_id,
                idempotency_key="concurrent-claims",
                model="test-model",
                dimensions=2,
                task_type="SEMANTIC_SIMILARITY",
                status="queued",
            ))
            session.flush()

            for number in range(4):
                prepared = prepare_input(
                    f"Test description {number}"
                )
                session.add(EmbeddingJobItem(
                    tenant_id=tenant,
                    id=str(uuid4()),
                    job_id=job_id,
                    source_type="image",
                    source_id=f"image-{number}",
                    input_text=prepared.text,
                    input_hash=prepared.input_hash,
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                ))

        def acquire_claim(_):
            barrier.wait(timeout=10)
            return repository.claim_next_embedding_item(
                tenant,
                job_id,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            claims = list(executor.map(
                acquire_claim,
                range(4),
            ))

        assert all(claim is not None for claim in claims)
        assert len({claim.item_id for claim in claims}) == 4
        assert len({claim.claim_token for claim in claims}) == 4
        assert all(claim.attempt == 1 for claim in claims)

        assert repository.claim_next_embedding_item(
            tenant, job_id
        ) is None

        with factory() as session:
            items = session.scalars(
                select(EmbeddingJobItem).where(
                    EmbeddingJobItem.tenant_id == tenant,
                    EmbeddingJobItem.job_id == job_id,
                )
            ).all()

            assert len(items) == 4
            assert all(
                item.status == "processing" for item in items
            )
            assert all(item.attempts == 1 for item in items)
            assert {
                item.claim_token for item in items
            } == {
                claim.claim_token for claim in claims
            }

    finally:
        # Delete only this test's committed job.
        # Its items are removed by ON DELETE CASCADE.
        with factory.begin() as session:
            session.execute(
                delete(EmbeddingJob).where(
                    EmbeddingJob.tenant_id == tenant,
                    EmbeddingJob.id == job_id,
                )
            )