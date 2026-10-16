from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import ImageEmbedding, PostEmbedding
from app.schemas.embedding import EmbeddingCacheKey
from app.services.embedding_vectors import normalize_embedding


def embedding_table(key: EmbeddingCacheKey):
    if key.source_type == "image":
        return ImageEmbedding, ImageEmbedding.image_id

    return PostEmbedding, PostEmbedding.post_id


def get_cached_embedding(
    key: EmbeddingCacheKey,
) -> list[float] | None:
    table, source_column = embedding_table(key)

    statement = select(table.vector).where(
        table.tenant_id == key.tenant_id,
        source_column == key.source_id,
        table.model == key.model,
        table.dimensions == key.dimensions,
        table.task_type == key.task_type,
        table.input_hash == key.input_hash,
    )

    with SessionLocal() as session:
        vector = session.execute(
            statement
        ).scalar_one_or_none()

    if vector is None:
        return None

    # Validate stored data before allowing it into ranking.
    return normalize_embedding(
        vector,
        expected_dimensions=key.dimensions,
    )


def save_cached_embedding(
    key: EmbeddingCacheKey,
    vector: list[float],
) -> bool:
    """Return True if inserted; False if the same key already exists."""
    normalized = normalize_embedding(
        vector,
        expected_dimensions=key.dimensions,
    )

    table, source_column = embedding_table(key)

    statement = insert(table).values(
        tenant_id=key.tenant_id,
        model=key.model,
        dimensions=key.dimensions,
        task_type=key.task_type,
        input_hash=key.input_hash,
        vector=normalized,
        **{source_column.key: key.source_id},
    )

    statement = statement.on_conflict_do_nothing(
        index_elements=[
            "tenant_id",
            source_column.key,
            "model",
            "dimensions",
            "task_type",
            "input_hash",
        ],
    ).returning(source_column)

    with SessionLocal.begin() as session:
        inserted_id = session.execute(
            statement
        ).scalar_one_or_none()

    return inserted_id is not None