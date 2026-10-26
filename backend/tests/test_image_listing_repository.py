from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image
from app.repositories import images as repository


pytestmark = pytest.mark.integration


@pytest.fixture
def image_listing_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    owner = f"ws_{uuid4().hex}"
    other = f"ws_{uuid4().hex}"
    empty = f"ws_{uuid4().hex}"
    now = datetime.now(timezone.utc)

    try:
        with factory.begin() as session:
            for tenant, image_id, checksum, created_at, creator in [
                (
                    owner, "img_001", "a" * 64,
                    now - timedelta(days=1), "Owner",
                ),
                (owner, "img_002", "b" * 64, now, "Owner"),
                (owner, "img_003", "c" * 64, now, "Owner"),
                (other, "img_003", "d" * 64, now, "Other creator"),
            ]:
                session.add(Image(
                    tenant_id=tenant,
                    id=image_id,
                    file_path=f"data/images/{image_id}.jpg",
                    checksum=checksum,
                    creator=creator,
                    source_url="",
                    license_url="",
                    status="pending",
                    created_at=created_at,
                ))

        yield SimpleNamespace(
            owner=owner,
            other=other,
            empty=empty,
        )
    finally:
        transaction.rollback()
        connection.close()


def test_pagination_has_stable_newest_first_order(
    image_listing_database,
):
    ctx = image_listing_database

    first = repository.list_images(ctx.owner, limit=2)

    assert [item.image_id for item in first.items] == [
        "img_003", "img_002"
    ]
    assert first.next_offset == 2

    second = repository.list_images(
        ctx.owner,
        offset=first.next_offset,
        limit=2,
    )

    assert [item.image_id for item in second.items] == ["img_001"]
    assert second.next_offset is None

    identifiers = [
        item.image_id for item in first.items + second.items
    ]
    assert len(identifiers) == len(set(identifiers))


def test_listing_is_scoped_to_workspace(image_listing_database):
    ctx = image_listing_database

    result = repository.list_images(ctx.other)

    assert len(result.items) == 1
    assert result.items[0].image_id == "img_003"
    assert result.items[0].creator == "Other creator"

    # Internal file paths and checksums are not part of this response.
    assert set(result.items[0].model_dump()) == {
        "image_id",
        "status",
        "creator",
        "created_at",
    }


def test_empty_workspace_has_no_next_page(image_listing_database):
    result = repository.list_images(image_listing_database.empty)

    assert result.items == []
    assert result.next_offset is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"offset": -1},
        {"offset": True},
        {"offset": 1.5},
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
    ],
)
def test_invalid_pagination_is_rejected(
    image_listing_database, arguments
):
    with pytest.raises(ValueError):
        repository.list_images(
            image_listing_database.owner,
            **arguments,
        )