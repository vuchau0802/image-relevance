
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Image, ImageMetadataRecord, Post
from app.repositories.embeddings import get_cached_embedding
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    prepare_image_input,
    prepare_post_input,
)
from app.services.similarity import cosine_similarity
from app.services.subject_guard import canonical_subject, subject_matches

class PostNotFoundError(ValueError):
    pass

class MissingPostEmbeddingError(ValueError):
    pass

def rank_post_images(
    tenant_id: str,
    post_id: str,
    top: int = 5,
) -> dict:
    if not tenant_id.strip() or len(tenant_id) > 50:
        raise ValueError("Invalid tenant_id")

    if not post_id.strip() or len(post_id) > 50:
        raise ValueError("Invalid post_id")

    if isinstance(top, bool) or not isinstance(top, int):
        raise ValueError("top must be an integer")

    if not 1 <= top <= 50:
        raise ValueError("top must be between 1 and 50")

    settings = get_settings()

    def cache_key(source_type, source_id, prepared):
        return EmbeddingCacheKey(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            task_type=EMBEDDING_TASK_TYPE,
            input_hash=prepared.input_hash,
        )

    with SessionLocal() as session:
        record = session.execute(
            select(Post).where(
                Post.tenant_id == tenant_id,
                Post.id == post_id,
            )
        ).scalar_one_or_none()

        if record is None:
            raise PostNotFoundError("Post not found for this tenant.")

        post = PostInput(
            id=record.id,
            title=record.title,
            content=record.content,
            required_subject=record.required_subject,
        )

        rows = session.execute(
            select(Image.id, ImageMetadataRecord)
            .join(
                ImageMetadataRecord,
                (
                    Image.tenant_id
                    == ImageMetadataRecord.tenant_id
                )
                & (
                    Image.id
                    == ImageMetadataRecord.image_id
                ),
            )
            .where(
                Image.tenant_id == tenant_id,
                Image.status == "completed",
            )
            .order_by(Image.id)
        ).all()

        candidates = [
            (
                image_id,
                ImageMetadata(
                    subject=metadata.subject,
                    category=metadata.category,
                    attributes=metadata.attributes,
                    caption=metadata.caption,
                    confidence=metadata.confidence,
                ),
            )
            for image_id, metadata in rows
        ]

    prepared_post = prepare_post_input(post)
    post_vector = get_cached_embedding(
        cache_key("post", post.id, prepared_post)
    )

    if post_vector is None:
        raise MissingPostEmbeddingError(
            "Current post embedding is missing."
        )

    ranked = []
    missing_embeddings = []
    rejected_subjects = []
    candidates_scored = 0

    for image_id, metadata in candidates:
        prepared_image = prepare_image_input(metadata)
        image_vector = get_cached_embedding(
            cache_key("image", image_id, prepared_image)
        )

        if image_vector is None:
            missing_embeddings.append(image_id)
            continue

        similarity = cosine_similarity(
            post_vector, image_vector
        )
        candidates_scored += 1

        if not subject_matches(
            post.required_subject,
            metadata.subject,
            category=metadata.category,
            caption=metadata.caption,
        ):
            rejected_subjects.append({
                "image_id": image_id,
                "subject": metadata.subject,
                "reason": "Subject mismatch or unsupported subject",
            })
            continue

        ranked.append({
            "image_id": image_id,
            "subject": metadata.subject,
            "caption": metadata.caption,
            "similarity": similarity,
        })

    ranked.sort(
        key=lambda item: (
            -item["similarity"],
            item["image_id"],
        )
    )

    subject_compatible_count = len(ranked)

    accepted = [
        item
        for item in ranked
        if item["similarity"] >= settings.min_match_similarity
    ]

    if canonical_subject(post.required_subject) is None:
        status = "unsupported_subject"
        reason = (
            "The required subject is not covered "
            "by the subject guard."
        )
    elif not candidates:
        status = "no_confident_match"
        reason = (
            "No completed images with metadata "
            "are available for this tenant."
        )
    elif missing_embeddings:
        status = "incomplete"
        reason = (
            "Some eligible images lack current embeddings. "
            "The ranking is provisional."
        )
    elif not ranked:
        status = "no_confident_match"
        reason = (
            "No image passed the required-subject guard."
        )
    elif not accepted:
        status = "no_confident_match"
        reason = (
            "Subject-compatible images were found, but none "
            "met the similarity threshold."
        )
    else:
        status = "matched"
        reason = (
            "Images passed the subject guard "
            "and similarity threshold."
        )

    return {
        "post_id": post.id,
        "status": status,
        "reason": reason,
        "required_subject": post.required_subject,
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "candidates_scored": candidates_scored,
        "subject_compatible_candidates": subject_compatible_count,
        "subject_rejected_count": len(rejected_subjects),
        "missing_current_embeddings": missing_embeddings,
        "results": accepted[:top],
    }
