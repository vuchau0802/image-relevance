from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, ImageMetadataRecord, Post
from app.repositories import embeddings
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput
from app.services import ranking
from app.services.embedding_text import (
    prepare_image_input,
    prepare_post_input,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def ranking_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    monkeypatch.setattr(ranking, "SessionLocal", factory)
    monkeypatch.setattr(embeddings, "SessionLocal", factory)
    monkeypatch.setattr(
        ranking,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="test-model",
            embedding_dimensions=2,
            min_match_similarity=0.5,
        ),
    )

    tenants = [f"test-{uuid4()}", f"test-{uuid4()}"]

    post = PostInput(
        id="shared-post",
        title="Red foxes",
        content="Observing red foxes outdoors.",
        required_subject="red fox",
    )

    metadata = ImageMetadata(
        subject="red fox",
        category="animal",
        attributes=["standing outdoors"],
        caption="A red fox outdoors.",
        confidence=0.99,
    )

    def key(tenant, source_type, source_id, prepared):
        return EmbeddingCacheKey(
            tenant_id=tenant,
            source_type=source_type,
            source_id=source_id,
            model="test-model",
            dimensions=2,
            input_hash=prepared.input_hash,
        )

    try:
        for index, tenant in enumerate(tenants):
            image_id = f"tenant-image-{index}"

            with factory.begin() as session:
                session.add(Post(
                    tenant_id=tenant,
                    **post.model_dump(),
                ))
                session.add(Image(
                    tenant_id=tenant,
                    id=image_id,
                    file_path="data/images/test.jpg",
                    checksum="a" * 64,
                    source_url="https://example.com/image",
                    creator="Test fixture",
                    license_url="https://example.com/license",
                    status="completed",
                ))
                session.flush()

                session.add(ImageMetadataRecord(
                    tenant_id=tenant,
                    image_id=image_id,
                    vision_model="test-vision",
                    **metadata.model_dump(),
                ))

            post_vector = (
                [1.0, 0.0] if index == 0 else [0.0, 1.0]
            )

            embeddings.save_cached_embedding(
                key(
                    tenant,
                    "post",
                    post.id,
                    prepare_post_input(post),
                ),
                post_vector,
            )
            embeddings.save_cached_embedding(
                key(
                    tenant,
                    "image",
                    image_id,
                    prepare_image_input(metadata),
                ),
                [0.6, 0.8],
            )

        yield tenants

    finally:
        transaction.rollback()
        connection.close()


def test_each_tenant_sees_only_its_images(ranking_database):
    first_tenant, second_tenant = ranking_database

    first = ranking.rank_post_images(
        first_tenant, "shared-post"
    )
    second = ranking.rank_post_images(
        second_tenant, "shared-post"
    )

    assert first["candidates_scored"] == 1
    assert second["candidates_scored"] == 1
    assert first["results"][0]["image_id"] == "tenant-image-0"
    assert second["results"][0]["image_id"] == "tenant-image-1"


def test_shared_post_id_uses_tenant_specific_vector(
    ranking_database,
):
    first_tenant, second_tenant = ranking_database

    first = ranking.rank_post_images(
        first_tenant, "shared-post"
    )
    second = ranking.rank_post_images(
        second_tenant, "shared-post"
    )

    assert first["results"][0]["similarity"] == pytest.approx(
        0.6
    )
    assert second["results"][0]["similarity"] == pytest.approx(
        0.8
    )


def test_unknown_tenant_cannot_read_post(ranking_database):
    with pytest.raises(ranking.PostNotFoundError):
        ranking.rank_post_images(
            f"test-{uuid4()}",
            "shared-post",
        )