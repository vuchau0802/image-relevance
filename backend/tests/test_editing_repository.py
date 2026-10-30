from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Post, PostEmbedding
from app.repositories import embeddings, posts
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.post import PostInput, PostUpdate
from app.services import ranking
from app.services.embedding_text import prepare_post_input


pytestmark = pytest.mark.integration


@pytest.fixture
def editing_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    monkeypatch.setattr(posts, "SessionLocal", factory)
    monkeypatch.setattr(embeddings, "SessionLocal", factory)
    monkeypatch.setattr(ranking, "SessionLocal", factory)
    monkeypatch.setattr(
        ranking,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="test-model",
            embedding_dimensions=2,
            min_match_similarity=0.85,
        ),
    )

    owner = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"
    original = PostInput(
        id="shared-post",
        title="Original title",
        content="Original red fox content.",
        required_subject="red fox",
    )
    key = EmbeddingCacheKey(
        tenant_id=owner,
        source_type="post",
        source_id=original.id,
        model="test-model",
        dimensions=2,
        input_hash=prepare_post_input(original).input_hash,
    )

    try:
        with factory.begin() as session:
            session.add(Post(
                tenant_id=owner,
                **original.model_dump(),
            ))
            session.add(Post(
                tenant_id=other,
                id="shared-post",
                title="Other owner's post",
                content="Private content.",
                required_subject="forest",
            ))
            session.add(Post(
                tenant_id=owner,
                id="owner-only",
                title="Owner-only post",
                content="Private red fox content.",
                required_subject="red fox",
            ))
            session.flush()
            session.add(PostEmbedding(
                tenant_id=owner,
                post_id=original.id,
                model=key.model,
                dimensions=key.dimensions,
                task_type=key.task_type,
                input_hash=key.input_hash,
                vector=[1.0, 0.0],
            ))

        yield SimpleNamespace(
            owner=owner,
            other=other,
            original=original,
            key=key,
        )
    finally:
        transaction.rollback()
        connection.close()


def original_payload(ctx):
    return ctx.original.model_dump(exclude={"id"})


def test_reads_owned_post(editing_database):
    ctx = editing_database

    detail = posts.get_post(ctx.owner, "shared-post")
    assert detail.model_dump() == {
        **ctx.original.model_dump(),
        "failed_preparation_job_id": None,
    }


def test_update_persists_without_changing_id_or_other_owner(
    editing_database,
):
    ctx = editing_database
    payload = PostUpdate(
        title=" Updated title ",
        content=" Updated forest content. ",
        required_subject=" forest ",
    )

    result = posts.update_post(ctx.owner, "shared-post", payload)

    assert result.id == "shared-post"
    assert result.title == "Updated title"
    assert result.content == "Updated forest content."
    assert result.required_subject == "forest"
    detail = posts.get_post(ctx.owner, "shared-post")
    assert detail.model_dump() == {
        **result.model_dump(),
        "failed_preparation_job_id": None,
    }

    other = posts.get_post(ctx.other, "shared-post")
    assert other.title == "Other owner's post"
    assert other.content == "Private content."


@pytest.mark.parametrize("operation", ["read", "update"])
def test_missing_post_is_not_created(editing_database, operation):
    ctx = editing_database

    with pytest.raises(posts.PostNotFoundError):
        if operation == "read":
            posts.get_post(ctx.owner, "missing-post")
        else:
            posts.update_post(
                ctx.owner,
                "missing-post",
                PostUpdate(**original_payload(ctx)),
            )


@pytest.mark.parametrize("operation", ["read", "update"])
def test_other_owner_cannot_read_or_edit_post(
    editing_database, operation
):
    ctx = editing_database

    with pytest.raises(posts.PostNotFoundError):
        if operation == "read":
            posts.get_post(ctx.other, "owner-only")
        else:
            posts.update_post(
                ctx.other,
                "owner-only",
                PostUpdate(**original_payload(ctx)),
            )

    assert posts.get_post(
        ctx.owner, "owner-only"
    ).title == "Owner-only post"


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "Changed title"),
        ("content", "Changed article content."),
        ("required_subject", "forest"),
    ],
)
def test_changed_input_requires_current_embedding(
    editing_database, field, value
):
    ctx = editing_database
    payload = original_payload(ctx)
    payload[field] = value

    posts.update_post(
        ctx.owner,
        "shared-post",
        PostUpdate(**payload),
    )

    with pytest.raises(ranking.MissingPostEmbeddingError):
        ranking.rank_post_images(ctx.owner, "shared-post")

    # Historical embeddings remain available under their original key.
    assert embeddings.get_cached_embedding(ctx.key) == [1.0, 0.0]


def test_unchanged_normalized_input_keeps_embedding_valid(
    editing_database,
):
    ctx = editing_database
    payload = {
        field: f"  {value}  "
        for field, value in original_payload(ctx).items()
    }

    updated = posts.update_post(
        ctx.owner,
        "shared-post",
        PostUpdate(**payload),
    )

    assert prepare_post_input(updated).input_hash == ctx.key.input_hash
    assert embeddings.get_cached_embedding(ctx.key) == [1.0, 0.0]


def test_update_payload_cannot_supply_post_id(editing_database):
    ctx = editing_database

    with pytest.raises(ValidationError):
        PostUpdate(
            id="replacement-id",
            **original_payload(ctx),
        )