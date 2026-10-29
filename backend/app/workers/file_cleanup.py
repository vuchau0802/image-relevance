import hashlib
import re
from datetime import timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image, ImageFileCleanupTask


class UnsafeImageCleanupError(ValueError):
    pass


def remove_upload_file(task: ImageFileCleanupTask) -> None:
    if (
        re.fullmatch(r"ws_[0-9a-f]{32}", task.tenant_id) is None
        or re.fullmatch(r"img_[0-9a-f]{32}", task.image_id) is None
    ):
        raise UnsafeImageCleanupError("Invalid upload identifiers")

    expected_relative = (
        f"data/uploads/{task.tenant_id}/{task.image_id}.jpg"
    )
    if task.file_path != expected_relative:
        raise UnsafeImageCleanupError("Unexpected upload path")

    project = PROJECT_ROOT.resolve()
    workspace = project / "data" / "uploads" / task.tenant_id
    path = workspace / f"{task.image_id}.jpg"

    # Reject symlinks or junctions redirecting the expected location.
    if workspace.resolve() != workspace or path.resolve() != path:
        raise UnsafeImageCleanupError("Upload path is redirected")

    # A previous attempt may have removed the file before its
    # database transaction finished.
    if not path.exists():
        return

    if not path.is_file():
        raise UnsafeImageCleanupError("Upload path is not a file")

    with path.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()

    if checksum != task.checksum:
        raise UnsafeImageCleanupError("Upload checksum changed")

    path.unlink(missing_ok=True)


def process_next_file_cleanup() -> Literal[
    "idle", "completed", "retry", "failed"
]:
    with SessionLocal.begin() as session:
        task = session.scalar(
            select(ImageFileCleanupTask)
            .where(
                ImageFileCleanupTask.status == "pending",
                ImageFileCleanupTask.available_at <= func.now(),
                ImageFileCleanupTask.attempts
                < ImageFileCleanupTask.max_attempts,
            )
            .order_by(
                ImageFileCleanupTask.created_at,
                ImageFileCleanupTask.tenant_id,
                ImageFileCleanupTask.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        if task is None:
            return "idle"

        now = session.scalar(select(func.clock_timestamp()))
        task.attempts += 1

        try:
            registered = session.scalar(
                select(Image.id)
                .where(
                    or_(
                        Image.file_path == task.file_path,
                        and_(
                            Image.tenant_id == task.tenant_id,
                            Image.id == task.image_id,
                        ),
                    )
                )
                .limit(1)
            )

            if registered is not None:
                raise UnsafeImageCleanupError(
                    "Image is still registered"
                )

            remove_upload_file(task)

        except UnsafeImageCleanupError as error:
            task.status = "failed"
            task.last_error = str(error)
            task.finished_at = now
            return "failed"

        except OSError as error:
            task.last_error = type(error).__name__

            if task.attempts >= task.max_attempts:
                task.status = "failed"
                task.finished_at = now
                return "failed"

            task.available_at = now + timedelta(
                seconds=min(300, 5 * (2 ** task.attempts))
            )
            return "retry"

        else:
            task.status = "completed"
            task.last_error = None
            task.finished_at = now
            return "completed"