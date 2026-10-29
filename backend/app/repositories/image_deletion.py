import re
from uuid import uuid4

from sqlalchemy import delete, exists, or_, select

from app.database import SessionLocal
from app.models import (
    EmbeddingJobItem,
    Image,
    ImageFileCleanupTask,
    Job,
    JobItem,
)
from app.repositories.jobs import refresh_job_status


class ImageNotFoundError(LookupError):
    pass


class ImageBusyError(ValueError):
    pass


class ImageDeletionNotAllowedError(ValueError):
    pass


def delete_image(
    tenant_id: str,
    image_id: str,
) -> str:
    with SessionLocal.begin() as session:
        if session.get(Image, (tenant_id, image_id)) is None:
            raise ImageNotFoundError("Image not found")

        def related_job_ids():
            return set(session.scalars(
                select(JobItem.job_id)
                .where(
                    JobItem.tenant_id == tenant_id,
                    JobItem.image_id == image_id,
                )
                .distinct()
            ).all())

        job_ids = related_job_ids()

        # Match the vision worker's parent-job-before-image lock order.
        jobs = session.scalars(
            select(Job)
            .where(
                Job.tenant_id == tenant_id,
                Job.id.in_(job_ids),
            )
            .order_by(Job.id)
            .with_for_update()
        ).all()

        image = session.get(
            Image,
            (tenant_id, image_id),
            with_for_update=True,
            populate_existing=True,
        )

        if image is None:
            raise ImageNotFoundError("Image not found")

        if related_job_ids() != job_ids:
            raise ImageBusyError(
                "Image processing changed. Try deleting again."
            )

        expected_path = (
            f"data/uploads/{tenant_id}/{image_id}.jpg"
        )
        if (
            re.fullmatch(r"ws_[0-9a-f]{32}", tenant_id) is None
            or re.fullmatch(r"img_[0-9a-f]{32}", image_id) is None
            or image.file_path != expected_path
        ):
            raise ImageDeletionNotAllowedError(
                "Only private uploaded images can be deleted"
            )

        vision_active = exists().where(
            JobItem.tenant_id == tenant_id,
            JobItem.image_id == image_id,
            JobItem.status.in_(["pending", "processing"]),
        )
        embedding_active = exists().where(
            EmbeddingJobItem.tenant_id == tenant_id,
            EmbeddingJobItem.source_type == "image",
            EmbeddingJobItem.source_id == image_id,
            EmbeddingJobItem.status.in_(["pending", "processing"]),
        )

        if session.scalar(
            select(or_(vision_active, embedding_active))
        ):
            raise ImageBusyError(
                "Image processing is queued or running. "
                "Wait for it to finish before deleting."
            )

        cleanup_id = str(uuid4())
        session.add(ImageFileCleanupTask(
            tenant_id=tenant_id,
            id=cleanup_id,
            image_id=image_id,
            file_path=image.file_path,
            checksum=image.checksum,
            status="pending",
            attempts=0,
            max_attempts=3,
        ))

        # Active items were rejected above. Remove finished vision
        # items to satisfy their foreign key to the image.
        session.execute(
            delete(JobItem).where(
                JobItem.tenant_id == tenant_id,
                JobItem.image_id == image_id,
            )
        )

        for job in jobs:
            refresh_job_status(session, job)

        # Metadata, embeddings, and image context cascade on deletion.
        session.delete(image)

    return cleanup_id