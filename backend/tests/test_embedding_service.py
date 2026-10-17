from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.repositories.usage import EmbeddingBudgetExceededError
from app.schemas.embedding import EmbeddingCacheKey
from app.services import embeddings as service
from app.services.embedding_text import prepare_input
from app.services.embedding_vectors import InvalidEmbeddingError


@pytest.fixture
def setup_service(monkeypatch):
    prepared = prepare_input("Subject: red fox")

    key = EmbeddingCacheKey(
        tenant_id="test-tenant",
        source_type="image",
        source_id="img_001",
        model="test-embedding-model",
        dimensions=3,
        input_hash=prepared.input_hash,
    )

    settings = SimpleNamespace(
        embedding_model=key.model,
        embedding_dimensions=3,
        embedding_daily_call_limit=10,
        gemini_api_key=SimpleNamespace(
            get_secret_value=lambda: "fake-test-key"
        ),
    )

    cache = {}

    def save_embedding(cache_key, vector):
        if cache_key in cache:
            return False
        cache[cache_key] = list(vector)
        return True

    reserve = Mock()
    finish = Mock()
    save = Mock(side_effect=save_embedding)

    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[
            SimpleNamespace(values=[3.0, 4.0, 0.0])
        ]
    )
    client_factory = Mock(return_value=client)

    monkeypatch.setattr(
        service, "get_settings", lambda: settings
    )
    monkeypatch.setattr(
        service,
        "get_cached_embedding",
        lambda cache_key: cache.get(cache_key),
    )
    monkeypatch.setattr(
        service, "save_cached_embedding", save
    )
    monkeypatch.setattr(
        service, "reserve_embedding_call", reserve
    )
    monkeypatch.setattr(
        service, "finish_ai_call", finish
    )
    monkeypatch.setattr(
        service.genai, "Client", client_factory
    )

    return SimpleNamespace(
        prepared=prepared,
        key=key,
        cache=cache,
        reserve=reserve,
        finish=finish,
        save=save,
        client=client,
        client_factory=client_factory,
    )


def test_cache_hit_does_not_request_or_reserve(setup_service):
    ctx = setup_service
    ctx.cache[ctx.key] = [0.6, 0.8, 0.0]

    result = service.get_or_create_embedding(
        ctx.key, ctx.prepared
    )

    assert result.cache_hit is True
    assert result.call_id is None
    assert result.vector == [0.6, 0.8, 0.0]
    ctx.reserve.assert_not_called()
    ctx.client_factory.assert_not_called()
    ctx.finish.assert_not_called()


@pytest.mark.parametrize("source_type", ["image", "post"])
def test_success_saves_vector_and_attributes_call(
    setup_service, source_type
):
    ctx = setup_service
    key = ctx.key.model_copy(
        update={
            "source_type": source_type,
            "source_id": "source_001",
        }
    )

    result = service.get_or_create_embedding(
        key, ctx.prepared
    )

    assert result.cache_hit is False
    assert result.call_id
    assert result.vector == pytest.approx([0.6, 0.8, 0.0])

    reservation = ctx.reserve.call_args.kwargs
    record = reservation["call_record"]

    assert reservation["tenant_id"] == key.tenant_id
    assert reservation["daily_limit"] == 10
    assert record["call_id"] == result.call_id
    assert record["operation"] == "embedding"
    assert record["model"] == key.model
    assert record["status"] == "started"
    assert record["image_id"] == (
        key.source_id if source_type == "image" else None
    )
    assert record["post_id"] == (
        key.source_id if source_type == "post" else None
    )

    request = ctx.client.models.embed_content.call_args.kwargs
    assert request["model"] == key.model
    assert request["contents"] == ctx.prepared.text
    assert request["config"].output_dimensionality == 3
    assert request["config"].task_type == "SEMANTIC_SIMILARITY"

    ctx.finish.assert_called_once_with(
        key.tenant_id,
        result.call_id,
        status="completed",
    )
    ctx.save.assert_called_once()
    ctx.client.close.assert_called_once()


def test_second_request_uses_cache(setup_service):
    ctx = setup_service

    first = service.get_or_create_embedding(
        ctx.key, ctx.prepared
    )
    second = service.get_or_create_embedding(
        ctx.key, ctx.prepared
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.vector == first.vector
    assert second.call_id is None
    ctx.reserve.assert_called_once()
    ctx.client.models.embed_content.assert_called_once()


def test_budget_block_does_not_construct_client(setup_service):
    ctx = setup_service
    ctx.reserve.side_effect = EmbeddingBudgetExceededError(
        "Daily embedding limit reached"
    )

    with pytest.raises(EmbeddingBudgetExceededError):
        service.get_or_create_embedding(
            ctx.key, ctx.prepared
        )

    ctx.client_factory.assert_not_called()
    ctx.finish.assert_not_called()
    ctx.save.assert_not_called()


@pytest.mark.parametrize(
    "returned_embeddings",
    [
        None,
        [],
        [SimpleNamespace(values=None)],
        [SimpleNamespace(values=[1.0, 2.0])],
        [SimpleNamespace(values=[0.0, 0.0, 0.0])],
    ],
)
def test_invalid_response_is_failed_and_not_cached(
    setup_service, returned_embeddings
):
    ctx = setup_service
    ctx.client.models.embed_content.return_value = (
        SimpleNamespace(embeddings=returned_embeddings)
    )

    with pytest.raises(InvalidEmbeddingError):
        service.get_or_create_embedding(
            ctx.key, ctx.prepared
        )

    assert ctx.finish.call_args.kwargs["status"] == "failed"
    assert (
        ctx.finish.call_args.kwargs["error_type"]
        == "InvalidEmbeddingError"
    )
    ctx.save.assert_not_called()
    ctx.client.close.assert_called_once()


def test_provider_timeout_is_logged_without_retry(setup_service):
    ctx = setup_service
    ctx.client.models.embed_content.side_effect = TimeoutError(
        "Simulated timeout"
    )

    with pytest.raises(TimeoutError):
        service.get_or_create_embedding(
            ctx.key, ctx.prepared
        )

    ctx.client.models.embed_content.assert_called_once()
    assert ctx.finish.call_args.kwargs["status"] == "failed"
    assert (
        ctx.finish.call_args.kwargs["error_type"]
        == "TimeoutError"
    )
    ctx.save.assert_not_called()
    ctx.client.close.assert_called_once()


def test_wrong_input_hash_is_rejected_before_reservation(
    setup_service,
):
    ctx = setup_service
    wrong_key = ctx.key.model_copy(
        update={"input_hash": "0" * 64}
    )

    with pytest.raises(ValueError, match="input hash"):
        service.get_or_create_embedding(
            wrong_key, ctx.prepared
        )

    ctx.reserve.assert_not_called()
    ctx.client_factory.assert_not_called()


def test_embedding_call_records_job_attribution(setup_service):
    ctx = setup_service

    result = service.get_or_create_embedding(
        ctx.key,
        ctx.prepared,
        job_id="11111111-1111-4111-8111-111111111111",
        job_item_id="22222222-2222-4222-8222-222222222222",
        attempt=2,
    )

    record = ctx.reserve.call_args.kwargs["call_record"]

    assert record["call_id"] == result.call_id
    assert record["job_id"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert record["job_item_id"] == (
        "22222222-2222-4222-8222-222222222222"
    )
    assert record["attempt"] == 2


@pytest.mark.parametrize(
    "attribution",
    [
        {"job_id": "job-only"},
        {
            "job_id": "job",
            "job_item_id": "item",
            "attempt": 0,
        },
        {
            "job_id": "job",
            "job_item_id": "item",
            "attempt": True,
        },
    ],
)
def test_invalid_job_attribution_prevents_request(
    setup_service, attribution
):
    ctx = setup_service

    with pytest.raises(ValueError, match="Job attribution"):
        service.get_or_create_embedding(
            ctx.key,
            ctx.prepared,
            **attribution,
        )

    ctx.reserve.assert_not_called()
    ctx.client_factory.assert_not_called()

def test_cache_write_failure_propagates_after_provider_success(
    setup_service,
):
    ctx = setup_service
    failure = RuntimeError("Simulated cache write failure")
    ctx.save.side_effect = failure

    with pytest.raises(RuntimeError) as caught:
        service.get_or_create_embedding(
            ctx.key,
            ctx.prepared,
        )

    assert caught.value is failure
    assert ctx.cache == {}

    ctx.reserve.assert_called_once()
    ctx.client.models.embed_content.assert_called_once()
    ctx.client.close.assert_called_once()

    # This records provider success, not cache persistence.
    ctx.finish.assert_called_once()
    assert ctx.finish.call_args.kwargs["status"] == "completed"


def test_retry_after_cache_write_failure_is_another_paid_attempt(
    setup_service,
):
    ctx = setup_service
    normal_save = ctx.save.side_effect
    ctx.save.side_effect = RuntimeError("Cache unavailable")

    with pytest.raises(RuntimeError):
        service.get_or_create_embedding(
            ctx.key,
            ctx.prepared,
        )

    ctx.save.side_effect = normal_save

    result = service.get_or_create_embedding(
        ctx.key,
        ctx.prepared,
    )

    assert result.cache_hit is False
    assert result.vector == pytest.approx([0.6, 0.8, 0.0])

    # Nothing was cached by the first attempt, so the retry
    # needs another reservation and provider request.
    assert ctx.reserve.call_count == 2
    assert ctx.client.models.embed_content.call_count == 2
    assert ctx.finish.call_count == 2