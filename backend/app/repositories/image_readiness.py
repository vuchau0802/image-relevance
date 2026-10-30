"""Read current image embedding readiness without per-image sessions."""

from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.models import EmbeddingJob, EmbeddingJobItem,ImageEmbedding, ImageMetadataRecord
from app.schemas.image import ImageMetadata
from app.services.embedding_text import EMBEDDING_TASK_TYPE, prepare_image_input
from app.services.embedding_vectors import InvalidEmbeddingError, normalize_embedding


def current_image_hashes(
    session, tenant_id: str, image_ids: set[str],
) -> dict[str, str]:
    if not image_ids:
        return {}

    metadata_rows = session.scalars(
        select(ImageMetadataRecord).where(
            ImageMetadataRecord.tenant_id == tenant_id,
            ImageMetadataRecord.image_id.in_(image_ids),
        )
    ).all()

    current_hashes = {}
    for record in metadata_rows:
        try:
            metadata = ImageMetadata(
                subject=record.subject,
                category=record.category,
                attributes=record.attributes,
                caption=record.caption,
                confidence=record.confidence,
            )
        except ValidationError:
            continue
        current_hashes[record.image_id] = prepare_image_input(metadata).input_hash

    return current_hashes


def ready_image_ids(
    session, tenant_id: str, image_ids: set[str],
    *, current_hashes: dict[str, str] | None = None,
) -> set[str]:
    if not image_ids:
        return set()

    settings = get_settings()
    if current_hashes is None:
        current_hashes = current_image_hashes(session, tenant_id, image_ids)
    else:
        current_hashes = {
            image_id: input_hash
            for image_id, input_hash in current_hashes.items()
            if image_id in image_ids
        }

    if not current_hashes:
        return set()

    embeddings = session.execute(
        select(
            ImageEmbedding.image_id,
            ImageEmbedding.input_hash,
            ImageEmbedding.vector,
        ).where(
            ImageEmbedding.tenant_id == tenant_id,
            ImageEmbedding.image_id.in_(current_hashes),
            ImageEmbedding.model == settings.embedding_model,
            ImageEmbedding.dimensions == settings.embedding_dimensions,
            ImageEmbedding.task_type == EMBEDDING_TASK_TYPE,
        )
    ).all()

    ready = set()
    for row in embeddings:
        if row.input_hash != current_hashes[row.image_id]:
            continue
        try:
            normalize_embedding(row.vector, settings.embedding_dimensions)
        except InvalidEmbeddingError:
            continue
        ready.add(row.image_id)

    return ready

def failed_image_preparation_jobs(
    session,
    tenant_id: str,
    image_ids: set[str],
    *, current_hashes: dict[str, str] | None = None,
) -> dict[str, str]:
    if not image_ids:
        return {}

    settings = get_settings()
    if current_hashes is None:
        current_hashes = current_image_hashes(session, tenant_id, image_ids)
    else:
        current_hashes = {
            image_id: input_hash
            for image_id, input_hash in current_hashes.items()
            if image_id in image_ids
        }

    if not current_hashes:
        return {}

    rows = session.execute(
        select(
            EmbeddingJobItem.source_id,
            EmbeddingJobItem.job_id,
            EmbeddingJobItem.input_hash,
            EmbeddingJobItem.status,
        )
        .join(
            EmbeddingJob,
            (
                EmbeddingJob.tenant_id
                == EmbeddingJobItem.tenant_id
            )
            & (EmbeddingJob.id == EmbeddingJobItem.job_id),
        )
        .where(
            EmbeddingJobItem.tenant_id == tenant_id,
            EmbeddingJobItem.source_type == "image",
            EmbeddingJobItem.source_id.in_(current_hashes),
            EmbeddingJobItem.status.in_(
                ["failed", "pending", "processing"]
            ),
            EmbeddingJob.model == settings.embedding_model,
            EmbeddingJob.dimensions
            == settings.embedding_dimensions,
            EmbeddingJob.task_type == EMBEDDING_TASK_TYPE,
        )
        .order_by(
            EmbeddingJobItem.created_at.desc(),
            EmbeddingJobItem.id.desc(),
        )
    ).all()

    failed = {}
    active = set()

    for row in rows:
        if row.input_hash != current_hashes[row.source_id]:
            continue

        if row.status in {"pending", "processing"}:
            active.add(row.source_id)
        else:
            failed.setdefault(row.source_id, row.job_id)

    return {
        image_id: job_id
        for image_id, job_id in failed.items()
        if image_id not in active
    }