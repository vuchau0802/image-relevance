from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, delete, text
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image
from app.repositories import uploads as repository
from app.services.upload_storage import StoredImageUpload
from app.repositories import image_deletion
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

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

@pytest.fixture
def limited_upload_database(upload_database, monkeypatch):
    ctx = upload_database
    monkeypatch.setattr(
        repository,
        "get_settings",
        lambda: SimpleNamespace(max_images_per_workspace=1),
    )
    monkeypatch.setattr(
        image_deletion, "SessionLocal", ctx.factory
    )
    return ctx


def test_new_upload_is_rejected_at_capacity(limited_upload_database):
    ctx = limited_upload_database
    original = stored_upload(ctx.tenant, checksum="a" * 64)
    rejected = stored_upload(ctx.tenant, checksum="b" * 64)

    repository.register_image_upload(
        ctx.tenant, original, creator="Original creator"
    )

    with pytest.raises(repository.ImageUploadLimitError):
        repository.register_image_upload(
            ctx.tenant, rejected, creator="Second creator"
        )

    assert image_count(ctx, ctx.tenant) == 1
    with ctx.factory() as session:
        assert session.get(
            Image, (ctx.tenant, original.image_id)
        ) is not None
        assert session.get(
            Image, (ctx.tenant, rejected.image_id)
        ) is None


def test_duplicate_upload_is_allowed_at_capacity(
    limited_upload_database,
):
    ctx = limited_upload_database
    original = stored_upload(ctx.tenant)
    duplicate = stored_upload(ctx.tenant)

    first = repository.register_image_upload(
        ctx.tenant, original, creator="Original creator"
    )
    repeated = repository.register_image_upload(
        ctx.tenant, duplicate, creator="Replacement creator"
    )

    assert repeated.image_id == first.image_id
    assert image_count(ctx, ctx.tenant) == 1

    with ctx.factory() as session:
        record = session.get(
            Image, (ctx.tenant, first.image_id)
        )
        assert record.creator == "Original creator"


def test_image_limit_is_independent_between_workspaces(
    limited_upload_database,
):
    ctx = limited_upload_database

    repository.register_image_upload(
        ctx.tenant,
        stored_upload(ctx.tenant),
        creator="First creator",
    )
    result = repository.register_image_upload(
        ctx.other,
        stored_upload(ctx.other),
        creator="Second creator",
    )

    assert result.status == "pending"
    assert image_count(ctx, ctx.tenant) == 1
    assert image_count(ctx, ctx.other) == 1


def test_deleting_image_frees_a_registration_slot(
    limited_upload_database,
):
    ctx = limited_upload_database
    original = stored_upload(ctx.tenant, checksum="a" * 64)

    repository.register_image_upload(
        ctx.tenant, original, creator="Original creator"
    )
    image_deletion.delete_image(
        tenant_id=ctx.tenant,
        image_id=original.image_id,
    )

    replacement = stored_upload(ctx.tenant, checksum="b" * 64)
    result = repository.register_image_upload(
        ctx.tenant, replacement, creator="Replacement creator"
    )

    assert result.image_id == replacement.image_id
    assert image_count(ctx, ctx.tenant) == 1

@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_uploads_respect_final_slot(
    monkeypatch, duplicate
):
    # This test commits across independent connections.
    # Never run it against the demo database.
    if not (engine.url.database or "").endswith("_test"):
        pytest.fail("Concurrency test requires a _test database")

    tenant = f"ws_{uuid4().hex}"
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    start = Barrier(2)

    @contextmanager
    def bounded_transaction():
        with factory.begin() as session:
            session.execute(
                text("SET LOCAL lock_timeout = '5s'")
            )
            session.execute(
                text("SET LOCAL statement_timeout = '10s'")
            )
            yield session

    monkeypatch.setattr(
        repository,
        "SessionLocal",
        SimpleNamespace(begin=bounded_transaction),
    )
    monkeypatch.setattr(
        repository,
        "get_settings",
        lambda: SimpleNamespace(max_images_per_workspace=1),
    )

    first = stored_upload(tenant, checksum="a" * 64)
    second = stored_upload(
        tenant,
        checksum=("a" if duplicate else "b") * 64,
    )

    def register(upload):
        start.wait(timeout=5)

        try:
            result = repository.register_image_upload(
                tenant,
                upload,
                creator="Concurrency test creator",
            )
        except repository.ImageUploadLimitError:
            return ("limited", None)

        return ("created", result.image_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(register, first),
                executor.submit(register, second),
            ]
            outcomes = [
                future.result(timeout=20)
                for future in futures
            ]

        with factory() as session:
            records = session.scalars(
                select(Image).where(Image.tenant_id == tenant)
            ).all()

        assert len(records) == 1

        if duplicate:
            # Both requests succeed but reuse one image.
            assert outcomes == [
                ("created", records[0].id),
                ("created", records[0].id),
            ]
        else:
            # Only one distinct image can take the final slot.
            assert sorted(
                outcome[0] for outcome in outcomes
            ) == ["created", "limited"]

            successful_id = next(
                image_id
                for status, image_id in outcomes
                if status == "created"
            )
            assert records[0].id == successful_id
    finally:
        # Remove only this test's randomly named workspace records.
        with factory.begin() as session:
            session.execute(
                delete(Image).where(Image.tenant_id == tenant)
            )