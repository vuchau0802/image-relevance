from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.repositories.embedding_jobs import (
    EmbeddingClaim,
    StaleEmbeddingClaimError,
)
from app.repositories.usage import EmbeddingBudgetExceededError
from app.schemas.embedding import EmbeddingCacheKey
from app.services.embedding_text import prepare_input
from app.services.embeddings import EmbeddingResult
from app.workers import embedding_runner as worker


@pytest.fixture
def worker_context(monkeypatch):
    prepared = prepare_input("Subject: red fox")

    claim = EmbeddingClaim(
        tenant_id="test-tenant",
        job_id="11111111-1111-4111-8111-111111111111",
        item_id="22222222-2222-4222-8222-222222222222",
        claim_token="33333333-3333-4333-8333-333333333333",
        attempt=1,
        key=EmbeddingCacheKey(
            tenant_id="test-tenant",
            source_type="image",
            source_id="img_test",
            model="test-model",
            dimensions=2,
            input_hash=prepared.input_hash,
        ),
        prepared=prepared,
    )

    embed = Mock(return_value=EmbeddingResult(
        vector=[1.0, 0.0],
        cache_hit=True,
        call_id=None,
    ))
    complete = Mock()
    fail = Mock(return_value="pending")
    release = Mock()

    monkeypatch.setattr(
        worker, "get_or_create_embedding", embed
    )
    monkeypatch.setattr(
        worker, "complete_embedding_claim", complete
    )
    monkeypatch.setattr(
        worker, "fail_embedding_claim", fail
    )
    monkeypatch.setattr(
        worker, "release_unstarted_embedding_claim", release
    )

    return SimpleNamespace(
        claim=claim,
        embed=embed,
        complete=complete,
        fail=fail,
        release=release,
    )


@pytest.mark.parametrize("cache_hit", [True, False])
def test_worker_completes_successful_embedding(
    worker_context, cache_hit
):
    ctx = worker_context
    ctx.embed.return_value = EmbeddingResult(
        vector=[1.0, 0.0],
        cache_hit=cache_hit,
        call_id=None if cache_hit else "test-call",
    )

    assert worker.process_embedding_claim(ctx.claim) is True

    ctx.embed.assert_called_once_with(
        ctx.claim.key,
        ctx.claim.prepared,
        job_id=ctx.claim.job_id,
        job_item_id=ctx.claim.item_id,
        attempt=ctx.claim.attempt,
    )
    ctx.complete.assert_called_once_with(
        ctx.claim,
        cache_hit=cache_hit,
    )
    ctx.fail.assert_not_called()
    ctx.release.assert_not_called()


def test_budget_block_releases_unstarted_claim(worker_context):
    ctx = worker_context
    ctx.embed.side_effect = EmbeddingBudgetExceededError(
        "Daily limit reached"
    )

    assert worker.process_embedding_claim(ctx.claim) is False

    ctx.release.assert_called_once_with(ctx.claim)
    ctx.complete.assert_not_called()
    ctx.fail.assert_not_called()


def test_timeout_uses_persistent_retry(worker_context):
    ctx = worker_context
    ctx.embed.side_effect = TimeoutError("Simulated timeout")

    assert worker.process_embedding_claim(ctx.claim) is False

    ctx.embed.assert_called_once()
    ctx.fail.assert_called_once_with(
        ctx.claim,
        retryable=True,
        error_type="TimeoutError",
    )
    ctx.complete.assert_not_called()
    ctx.release.assert_not_called()


def test_permanent_error_is_not_retryable(worker_context):
    ctx = worker_context
    ctx.embed.side_effect = ValueError("Invalid input")

    assert worker.process_embedding_claim(ctx.claim) is False

    ctx.fail.assert_called_once_with(
        ctx.claim,
        retryable=False,
        error_type="ValueError",
    )
    ctx.complete.assert_not_called()
    ctx.release.assert_not_called()


def test_stale_completion_does_not_mutate_new_owner(
    worker_context,
):
    ctx = worker_context
    ctx.complete.side_effect = StaleEmbeddingClaimError(
        "Ownership changed"
    )

    assert worker.process_embedding_claim(ctx.claim) is False

    ctx.fail.assert_not_called()
    ctx.release.assert_not_called()


def test_expired_budget_release_stops_safely(worker_context):
    ctx = worker_context
    ctx.embed.side_effect = EmbeddingBudgetExceededError(
        "Daily limit reached"
    )
    ctx.release.side_effect = StaleEmbeddingClaimError(
        "Lease expired"
    )

    assert worker.process_embedding_claim(ctx.claim) is False

    ctx.release.assert_called_once_with(ctx.claim)
    ctx.fail.assert_not_called()
    ctx.complete.assert_not_called()