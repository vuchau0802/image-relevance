import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Image, ImageFileCleanupTask
from app.workers import file_cleanup as cleanup


pytestmark = pytest.mark.integration


@pytest.fixture
def cleanup_database(monkeypatch, tmp_path):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(cleanup, "SessionLocal", factory)
    monkeypatch.setattr(cleanup, "PROJECT_ROOT", tmp_path)

    tenant = f"ws_{uuid4().hex}"
    image_id = f"img_{uuid4().hex}"
    relative = f"data/uploads/{tenant}/{image_id}.jpg"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    data = b"Synthetic cleanup test file"
    path.write_bytes(data)

    try:
        yield SimpleNamespace(
            factory=factory,
            tenant=tenant,
            image_id=image_id,
            relative=relative,
            path=path,
            root=tmp_path,
            checksum=hashlib.sha256(data).hexdigest(),
        )
    finally:
        transaction.rollback()
        connection.close()


def add_task(ctx, **overrides):
    task_id = str(uuid4())
    values = {
        "tenant_id": ctx.tenant,
        "id": task_id,
        "image_id": ctx.image_id,
        "file_path": ctx.relative,
        "checksum": ctx.checksum,
        "status": "pending",
        "attempts": 0,
        "max_attempts": 3,
    }
    values.update(overrides)

    with ctx.factory.begin() as session:
        session.add(ImageFileCleanupTask(**values))

    return task_id


def read_task(ctx, task_id):
    with ctx.factory() as session:
        return session.get(
            ImageFileCleanupTask,
            (ctx.tenant, task_id),
        )


def test_empty_queue_does_not_touch_files(cleanup_database):
    ctx = cleanup_database

    assert cleanup.process_next_file_cleanup() == "idle"
    assert ctx.path.is_file()


def test_matching_file_is_removed_and_task_completed(cleanup_database):
    ctx = cleanup_database
    task_id = add_task(ctx)

    assert cleanup.process_next_file_cleanup() == "completed"
    assert not ctx.path.exists()

    task = read_task(ctx, task_id)
    assert task.status == "completed"
    assert task.attempts == 1
    assert task.finished_at is not None
    assert task.last_error is None

    assert cleanup.process_next_file_cleanup() == "idle"
    assert read_task(ctx, task_id).attempts == 1


def test_missing_file_counts_as_completed(cleanup_database):
    ctx = cleanup_database
    task_id = add_task(ctx)
    ctx.path.unlink()

    assert cleanup.process_next_file_cleanup() == "completed"
    assert read_task(ctx, task_id).status == "completed"


def test_temporary_file_error_schedules_retry(
    cleanup_database, monkeypatch
):
    ctx = cleanup_database
    task_id = add_task(ctx)
    original_available = read_task(ctx, task_id).available_at

    monkeypatch.setattr(
        cleanup,
        "remove_upload_file",
        Mock(side_effect=PermissionError("Temporarily locked")),
    )

    assert cleanup.process_next_file_cleanup() == "retry"

    task = read_task(ctx, task_id)
    assert task.status == "pending"
    assert task.attempts == 1
    assert task.last_error == "PermissionError"
    assert task.available_at > original_available
    assert ctx.path.is_file()

    assert cleanup.process_next_file_cleanup() == "idle"


def test_final_file_error_marks_task_failed(
    cleanup_database, monkeypatch
):
    ctx = cleanup_database
    task_id = add_task(ctx, attempts=2)
    monkeypatch.setattr(
        cleanup,
        "remove_upload_file",
        Mock(side_effect=PermissionError("Temporarily locked")),
    )

    assert cleanup.process_next_file_cleanup() == "failed"

    task = read_task(ctx, task_id)
    assert task.status == "failed"
    assert task.attempts == 3
    assert task.finished_at is not None
    assert ctx.path.is_file()


def test_changed_checksum_preserves_file(cleanup_database):
    ctx = cleanup_database
    task_id = add_task(ctx)
    ctx.path.write_bytes(b"Different file contents")

    assert cleanup.process_next_file_cleanup() == "failed"
    assert ctx.path.read_bytes() == b"Different file contents"
    assert read_task(ctx, task_id).last_error == "Upload checksum changed"


@pytest.mark.parametrize("reference", ["same-image", "same-path"])
def test_registered_image_is_protected(cleanup_database, reference):
    ctx = cleanup_database
    task_id = add_task(ctx)

    with ctx.factory.begin() as session:
        session.add(Image(
            tenant_id=(
                ctx.tenant if reference == "same-image"
                else f"ws_{uuid4().hex}"
            ),
            id=(
                ctx.image_id if reference == "same-image"
                else f"img_{uuid4().hex}"
            ),
            file_path=ctx.relative,
            checksum=ctx.checksum,
            creator="Test creator",
            source_url="",
            license_url="",
            status="completed",
        ))

    assert cleanup.process_next_file_cleanup() == "failed"
    assert ctx.path.is_file()
    assert read_task(ctx, task_id).last_error == "Image is still registered"


@pytest.mark.parametrize(
    "file_path",
    [
        "../outside.jpg",
        "data/images/img_001.jpg",
        f"data/uploads/ws_{'b' * 32}/img_{'c' * 32}.jpg",
    ],
)
def test_unexpected_paths_are_rejected(cleanup_database, file_path):
    ctx = cleanup_database
    task_id = add_task(ctx, file_path=file_path)
    protected = ctx.root / "outside.jpg"
    protected.write_bytes(b"Keep this file")

    assert cleanup.process_next_file_cleanup() == "failed"
    assert ctx.path.is_file()
    assert protected.read_bytes() == b"Keep this file"
    assert read_task(ctx, task_id).status == "failed"


def test_future_task_is_not_processed(cleanup_database):
    ctx = cleanup_database
    task_id = add_task(
        ctx,
        available_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert cleanup.process_next_file_cleanup() == "idle"
    assert ctx.path.is_file()
    assert read_task(ctx, task_id).attempts == 0


def test_retry_recovers_after_interruption_following_file_removal(
    cleanup_database, monkeypatch
):
    ctx = cleanup_database
    task_id = add_task(ctx)
    original_remove = cleanup.remove_upload_file

    def remove_then_interrupt(task):
        original_remove(task)
        raise RuntimeError("Simulated interruption after file removal")

    monkeypatch.setattr(
        cleanup, "remove_upload_file", remove_then_interrupt
    )

    with pytest.raises(RuntimeError, match="Simulated interruption"):
        cleanup.process_next_file_cleanup()

    assert not ctx.path.exists()
    assert read_task(ctx, task_id).status == "pending"
    assert read_task(ctx, task_id).attempts == 0

    monkeypatch.setattr(cleanup, "remove_upload_file", original_remove)

    assert cleanup.process_next_file_cleanup() == "completed"
    assert read_task(ctx, task_id).status == "completed"