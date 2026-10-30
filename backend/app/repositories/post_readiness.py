from sqlalchemy import select

from app.config import get_settings
from app.models import EmbeddingJob, EmbeddingJobItem, PostEmbedding
from app.schemas.post import PostInput
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    prepare_post_input,
)
from app.services.embedding_vectors import (
    InvalidEmbeddingError,
    normalize_embedding,
)


def failed_post_preparation_job(
    session,
    tenant_id: str,
    post: PostInput,
) -> str | None:
    settings = get_settings()
    prepared = prepare_post_input(post)

    cached = session.scalar(
        select(PostEmbedding).where(
            PostEmbedding.tenant_id == tenant_id,
            PostEmbedding.post_id == post.id,
            PostEmbedding.input_hash == prepared.input_hash,
            PostEmbedding.model == settings.embedding_model,
            PostEmbedding.dimensions == settings.embedding_dimensions,
            PostEmbedding.task_type == EMBEDDING_TASK_TYPE,
        )
    )

    if cached is not None:
        try:
            normalize_embedding(
                cached.vector, settings.embedding_dimensions
            )
        except InvalidEmbeddingError:
            pass
        else:
            return None

    rows = session.execute(
        select(
            EmbeddingJobItem.job_id,
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
            EmbeddingJobItem.source_type == "post",
            EmbeddingJobItem.source_id == post.id,
            EmbeddingJobItem.input_hash == prepared.input_hash,
            EmbeddingJobItem.status.in_(
                ["failed", "pending", "processing"]
            ),
            EmbeddingJob.model == settings.embedding_model,
            EmbeddingJob.dimensions == settings.embedding_dimensions,
            EmbeddingJob.task_type == EMBEDDING_TASK_TYPE,
        )
        .order_by(
            EmbeddingJobItem.created_at.desc(),
            EmbeddingJobItem.id.desc(),
        )
    ).all()

    if any(
        row.status in {"pending", "processing"}
        for row in rows
    ):
        return None

    return next(
        (
            row.job_id for row in rows
            if row.status == "failed"
        ),
        None,
    )