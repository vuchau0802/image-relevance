from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image
from app.repositories import uploads as repository
from app.services.upload_storage import StoredImageUpload


pytestmark = pytest.mark.integration


@pytest.fixture
def upload_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(repository, "SessionLocal", factory)

    try:
        yield SimpleNamespace(
            factory=factory,
            tenant=f"ws_{uuid4().hex}",
            other=f"ws_{uuid4().hex}",
        )
    finally:
        transaction.rollback()
        connection.close()


def stored_upload(tenant, checksum="a" * 64):
    image_id = f"img_{uuid4().hex}"
    return StoredImageUpload(
        image_id=image_id,
        file_path=f"data/uploads/{tenant}/{image_id}.jpg",
        checksum=checksum,
        width=12,
        height=8,
    )


def image_count(ctx, tenant):
    with ctx.factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.tenant_id == tenant)
        )


def test_new_upload_is_persisted_as_pending(upload_database):
    ctx = upload_database
    upload = stored_upload(ctx.tenant)

    result = repository.register_image_upload(
        ctx.tenant,
        upload,
        creator="  Example photographer  ",
        source_url="https://example.com/photo",
        license_url="https://example.com/license",
    )

    assert result.image_id == upload.image_id
    assert result.status == "pending"

    with ctx.factory() as session:
        record = session.get(Image, (ctx.tenant, result.image_id))
        assert record.file_path == upload.file_path
        assert record.checksum == upload.checksum
        assert record.creator == "Example photographer"
        assert record.source_url == "https://example.com/photo"
        assert record.license_url == "https://example.com/license"


def test_duplicate_checksum_returns_existing_image(upload_database):
    ctx = upload_database
    first = stored_upload(ctx.tenant)
    duplicate = stored_upload(ctx.tenant)

    original = repository.register_image_upload(
        ctx.tenant, first, creator="Original creator"
    )
    repeated = repository.register_image_upload(
        ctx.tenant, duplicate, creator="Another creator"
    )

    assert repeated.image_id == original.image_id
    assert image_count(ctx, ctx.tenant) == 1

    with ctx.factory() as session:
        assert session.get(
            Image, (ctx.tenant, duplicate.image_id)
        ) is None


def test_duplicate_preserves_status_path_and_attribution(upload_database):
    ctx = upload_database
    original = stored_upload(ctx.tenant)

    repository.register_image_upload(
        ctx.tenant,
        original,
        creator="Original creator",
        source_url="https://example.com/original",
    )

    with ctx.factory.begin() as session:
        record = session.get(Image, (ctx.tenant, original.image_id))
        record.status = "completed"

    result = repository.register_image_upload(
        ctx.tenant,
        stored_upload(ctx.tenant),
        creator="Replacement creator",
        source_url="https://example.com/replacement",
    )

    assert result.status == "completed"

    with ctx.factory() as session:
        record = session.get(Image, (ctx.tenant, result.image_id))
        assert record.file_path == original.file_path
        assert record.creator == "Original creator"
        assert record.source_url == "https://example.com/original"


def test_same_checksum_is_independent_between_workspaces(upload_database):
    ctx = upload_database

    first = repository.register_image_upload(
        ctx.tenant, stored_upload(ctx.tenant), creator="First creator"
    )
    second = repository.register_image_upload(
        ctx.other, stored_upload(ctx.other), creator="Second creator"
    )

    assert first.image_id != second.image_id
    assert image_count(ctx, ctx.tenant) == 1
    assert image_count(ctx, ctx.other) == 1

    with ctx.factory() as session:
        assert session.get(
            Image, (ctx.other, first.image_id)
        ) is None


def test_other_workspace_path_is_rejected(upload_database):
    ctx = upload_database
    upload = stored_upload(ctx.tenant)
    forged = replace(
        upload,
        file_path=f"data/uploads/{ctx.other}/{upload.image_id}.jpg",
    )

    with pytest.raises(ValueError, match="workspace"):
        repository.register_image_upload(
            ctx.tenant, forged, creator="Example creator"
        )

    assert image_count(ctx, ctx.tenant) == 0


@pytest.mark.parametrize("creator", ["", "   ", "x" * 201])
def test_invalid_creator_creates_no_record(upload_database, creator):
    ctx = upload_database

    with pytest.raises(ValueError, match="creator"):
        repository.register_image_upload(
            ctx.tenant,
            stored_upload(ctx.tenant),
            creator=creator,
        )

    assert image_count(ctx, ctx.tenant) == 0