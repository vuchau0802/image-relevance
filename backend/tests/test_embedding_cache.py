from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, ImageEmbedding, Post
from app.repositories import embeddings as repository
from app.schemas.embedding import EmbeddingCacheKey
from app.services.embedding_vectors import InvalidEmbeddingError


pytestmark = pytest.mark.integration


@pytest.fixture
def cache_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    tenants = [f"test-{uuid4()}", f"test-{uuid4()}"]

    try:
        with factory.begin() as session:
            for tenant in tenants:
                session.add(Image(
                    tenant_id=tenant,
                    id="shared-source",
                    file_path="data/images/test.jpg",
                    checksum="a" * 64,
                    source_url="https://example.com/image",
                    creator="Test fixture",
                    license_url="https://example.com/license",
                    status="completed",
                ))
                session.add(Post(
                    tenant_id=tenant,
                    id="shared-source",
                    title="Test article",
                    content="An article about red foxes.",
                    required_subject="red fox",
                ))

        yield tenants, factory

    finally:
        transaction.rollback()
        connection.close()


def cache_key(tenant, **changes):
    data = {
        "tenant_id": tenant,
        "source_type": "image",
        "source_id": "shared-source",
        "model": "test-embedding-model",
        "dimensions": 2,
        "task_type": "SEMANTIC_SIMILARITY",
        "input_hash": "a" * 64,
    }
    return EmbeddingCacheKey.model_validate(data | changes)


def test_cache_miss_then_normalized_hit(cache_database):
    tenants, _ = cache_database
    key = cache_key(tenants[0])

    assert repository.get_cached_embedding(key) is None
    assert repository.save_cached_embedding(key, [3.0, 4.0])

    assert repository.get_cached_embedding(key) == pytest.approx(
        [0.6, 0.8]
    )


def test_duplicate_write_preserves_first_vector(cache_database):
    tenants, factory = cache_database
    key = cache_key(tenants[0])

    assert repository.save_cached_embedding(key, [3.0, 4.0])
    assert not repository.save_cached_embedding(key, [4.0, 3.0])

    assert repository.get_cached_embedding(key) == pytest.approx(
        [0.6, 0.8]
    )

    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ImageEmbedding)
            .where(ImageEmbedding.tenant_id == tenants[0])
        )
        assert count == 1


def test_changed_input_hash_requires_separate_embedding(cache_database):
    tenants, _ = cache_database
    original = cache_key(tenants[0])
    changed = cache_key(tenants[0], input_hash="b" * 64)

    repository.save_cached_embedding(original, [3.0, 4.0])

    assert repository.get_cached_embedding(changed) is None

    repository.save_cached_embedding(changed, [0.0, 1.0])

    assert repository.get_cached_embedding(original) == pytest.approx(
        [0.6, 0.8]
    )
    assert repository.get_cached_embedding(changed) == pytest.approx(
        [0.0, 1.0]
    )


def test_different_model_or_dimensions_is_cache_miss(cache_database):
    tenants, _ = cache_database
    original = cache_key(tenants[0])

    repository.save_cached_embedding(original, [3.0, 4.0])

    different_model = cache_key(
        tenants[0],
        model="another-model",
    )
    different_dimensions = cache_key(
        tenants[0],
        dimensions=3,
    )

    assert repository.get_cached_embedding(different_model) is None
    assert repository.get_cached_embedding(different_dimensions) is None


def test_tenants_have_separate_cache_entries(cache_database):
    tenants, _ = cache_database
    first = cache_key(tenants[0])
    second = cache_key(tenants[1])

    repository.save_cached_embedding(first, [3.0, 4.0])

    assert repository.get_cached_embedding(second) is None

    repository.save_cached_embedding(second, [0.0, 1.0])

    assert repository.get_cached_embedding(first) == pytest.approx(
        [0.6, 0.8]
    )
    assert repository.get_cached_embedding(second) == pytest.approx(
        [0.0, 1.0]
    )


def test_image_and_post_caches_are_separate(cache_database):
    tenants, _ = cache_database
    image_key = cache_key(tenants[0])
    post_key = cache_key(tenants[0], source_type="post")

    repository.save_cached_embedding(image_key, [3.0, 4.0])

    assert repository.get_cached_embedding(post_key) is None

    repository.save_cached_embedding(post_key, [0.0, 1.0])

    assert repository.get_cached_embedding(image_key) == pytest.approx(
        [0.6, 0.8]
    )
    assert repository.get_cached_embedding(post_key) == pytest.approx(
        [0.0, 1.0]
    )


def test_missing_source_is_rejected_by_foreign_key(cache_database):
    tenants, _ = cache_database
    key = cache_key(tenants[0], source_id="missing-source")

    with pytest.raises(IntegrityError):
        repository.save_cached_embedding(key, [3.0, 4.0])


def test_invalid_vector_is_not_stored(cache_database):
    tenants, _ = cache_database
    key = cache_key(tenants[0])

    with pytest.raises(InvalidEmbeddingError):
        repository.save_cached_embedding(key, [0.0, 0.0])

    assert repository.get_cached_embedding(key) is None