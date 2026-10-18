from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Post, PostContextRecord
from app.repositories import context as repository
from app.schemas.context import (
    ContextRequirement,
    ContextRequirements,
)
from app.schemas.post import PostInput
from app.services.embedding_text import prepare_post_input


pytestmark = pytest.mark.integration


@pytest.fixture
def context_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(
        repository, "SessionLocal", factory
    )

    tenants = [f"test-{uuid4()}", f"test-{uuid4()}"]

    post = PostInput(
        id="shared-post",
        title="Foxes in snow",
        content="A red fox in a snowy landscape.",
        required_subject="red fox",
    )

    requirements = ContextRequirements(requirements=[
        ContextRequirement(
            feature="snow",
            expected="present",
        )
    ])

    try:
        with factory.begin() as session:
            for tenant in tenants:
                session.add(Post(
                    tenant_id=tenant,
                    **post.model_dump(),
                ))

        yield SimpleNamespace(
            factory=factory,
            tenants=tenants,
            post_id=post.id,
            input_hash=prepare_post_input(post).input_hash,
            requirements=requirements,
        )

    finally:
        transaction.rollback()
        connection.close()


def save_context(ctx, **changes):
    arguments = {
        "tenant_id": ctx.tenants[0],
        "post_id": ctx.post_id,
        "input_hash": ctx.input_hash,
        "version": "manual-v1",
        "requirements": ctx.requirements,
        "reviewed": True,
    }
    arguments.update(changes)
    return repository.save_post_context(**arguments)


def read_context(ctx, **changes):
    arguments = {
        "tenant_id": ctx.tenants[0],
        "post_id": ctx.post_id,
        "version": "manual-v1",
    }
    arguments.update(changes)
    return repository.get_current_post_context(**arguments)


def test_reviewed_requirements_round_trip(context_database):
    ctx = context_database

    assert save_context(ctx) is True
    assert read_context(ctx) == ctx.requirements


def test_missing_context_returns_unknown(context_database):
    assert read_context(context_database) is None


def test_unreviewed_context_is_not_returned(context_database):
    ctx = context_database

    save_context(ctx, reviewed=False)

    assert read_context(ctx) is None


def test_reviewed_empty_requirements_are_explicit(
    context_database,
):
    ctx = context_database

    save_context(
        ctx,
        requirements=ContextRequirements(),
    )

    result = read_context(ctx)

    assert result is not None
    assert result.requirements == []


def test_identical_save_is_idempotent(context_database):
    ctx = context_database

    assert save_context(ctx) is True
    assert save_context(ctx) is False

    with ctx.factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(PostContextRecord)
            .where(
                PostContextRecord.tenant_id
                == ctx.tenants[0],
            )
        )
        assert count == 1


def test_existing_version_cannot_change_requirements(
    context_database,
):
    ctx = context_database
    save_context(ctx)

    changed = ContextRequirements(requirements=[
        ContextRequirement(
            feature="snow",
            expected="absent",
        )
    ])

    with pytest.raises(ValueError, match="new version"):
        save_context(ctx, requirements=changed)

    assert read_context(ctx) == ctx.requirements


def test_review_status_change_requires_new_version(
    context_database,
):
    ctx = context_database
    save_context(ctx, reviewed=False)

    with pytest.raises(ValueError, match="new version"):
        save_context(ctx, reviewed=True)

    assert save_context(
        ctx,
        version="manual-v2",
        reviewed=True,
    ) is True

    assert read_context(ctx) is None
    assert read_context(
        ctx, version="manual-v2"
    ) == ctx.requirements


def test_changed_post_invalidates_old_context(
    context_database,
):
    ctx = context_database
    save_context(ctx)

    with ctx.factory.begin() as session:
        post = session.get(
            Post,
            (ctx.tenants[0], ctx.post_id),
        )
        post.content = "A red fox resting in summer grass."

    assert read_context(ctx) is None

    with pytest.raises(ValueError, match="stale"):
        save_context(ctx, version="manual-v2")

    # The old record remains as history.
    with ctx.factory() as session:
        old = session.get(
            PostContextRecord,
            (
                ctx.tenants[0],
                ctx.post_id,
                ctx.input_hash,
                "manual-v1",
            ),
        )
        assert old is not None


def test_shared_post_id_is_isolated_by_tenant(
    context_database,
):
    ctx = context_database
    save_context(ctx)

    assert read_context(
        ctx,
        tenant_id=ctx.tenants[1],
    ) is None

    save_context(
        ctx,
        tenant_id=ctx.tenants[1],
        requirements=ContextRequirements(),
    )

    assert read_context(ctx) == ctx.requirements
    assert read_context(
        ctx,
        tenant_id=ctx.tenants[1],
    ).requirements == []