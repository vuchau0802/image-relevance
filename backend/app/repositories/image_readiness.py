"""Read current image embedding readiness without per-image sessions."""

from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.models import ImageEmbedding, ImageMetadataRecord
from app.schemas.image import ImageMetadata
from app.services.embedding_text import EMBEDDING_TASK_TYPE, prepare_image_input
from app.services.embedding_vectors import InvalidEmbeddingError, normalize_embedding


def ready_image_ids(session, tenant_id: str, image_ids: set[str]) -> set[str]:
    if not image_ids:
        return set()

    settings = get_settings()
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
