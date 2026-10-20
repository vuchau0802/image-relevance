from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Post
from app.repositories import posts


pytestmark = pytest.mark.integration


@pytest.fixture
def post_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(posts, "SessionLocal", factory)

    suffix = uuid4().hex
    tenant = f"posts_{suffix}"
    other = f"other_{suffix}"

    try:
        with factory.begin() as session:
            # Deliberately insert out of order.
            for number in (3, 1, 2):
                session.add(Post(
                    tenant_id=tenant,
                    id=f"post_{number:03}",
                    title=f"Own post {number}",
                    content="Synthetic repository test content.",
                    required_subject="red fox",
                ))

            # Same post ID, different tenant.
            session.add(Post(
                tenant_id=other,
                id="post_001",
                title="Other tenant's post",
                content="Synthetic content belonging to another tenant.",
                required_subject="motor scooter",
            ))

        yield tenant, other
    finally:
        transaction.rollback()
        connection.close()


def test_pages_are_ordered_without_overlap(post_database):
    tenant, _ = post_database

    first = posts.list_posts(tenant, offset=0, limit=2)
    second = posts.list_posts(
        tenant, offset=first.next_offset, limit=2
    )

    assert [item.id for item in first.items] == [
        "post_001", "post_002"
    ]
    assert first.next_offset == 2

    assert [item.id for item in second.items] == ["post_003"]
    assert second.next_offset is None


def test_exact_page_size_has_no_next_page(post_database):
    tenant, _ = post_database

    result = posts.list_posts(tenant, offset=0, limit=3)

    assert len(result.items) == 3
    assert result.next_offset is None


def test_same_id_is_isolated_by_tenant(post_database):
    tenant, other = post_database

    own = posts.list_posts(tenant)
    other_result = posts.list_posts(other)

    assert [item.title for item in own.items] == [
        "Own post 1", "Own post 2", "Own post 3"
    ]
    assert len(other_result.items) == 1
    assert other_result.items[0].id == "post_001"
    assert other_result.items[0].title == "Other tenant's post"
    assert other_result.items[0].required_subject == "motor scooter"


def test_offset_after_last_post_returns_empty_page(post_database):
    tenant, _ = post_database

    result = posts.list_posts(tenant, offset=100, limit=2)

    assert result.items == []
    assert result.next_offset is None