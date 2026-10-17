import json

from app.config import PROJECT_ROOT, get_settings
from app.database import SessionLocal
from app.models import Image, ImageMetadataRecord, Post
from app.repositories.embeddings import get_cached_embedding
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput, validate_post_corpus
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    prepare_image_input,
    prepare_post_input,
)


def get_demo_readiness() -> dict:
    settings = get_settings()

    manifest = json.loads(
        (PROJECT_ROOT / "data" / "manifest.json").read_text(
            encoding="utf-8-sig"
        )
    )
    expected_posts = validate_post_corpus(json.loads(
        (PROJECT_ROOT / "data" / "posts.json").read_text(
            encoding="utf-8-sig"
        )
    ))

    source_issues = []
    inputs = []

    with SessionLocal() as session:
        for entry in manifest:
            image_id = entry["id"]
            image = session.get(Image, ("demo", image_id))

            if image is None or image.status != "completed":
                source_issues.append({
                    "source_type": "image",
                    "source_id": image_id,
                    "reason": (
                        "missing" if image is None
                        else f"status={image.status}"
                    ),
                })
                continue

            record = session.get(
                ImageMetadataRecord,
                ("demo", image_id),
            )

            if record is None:
                source_issues.append({
                    "source_type": "image",
                    "source_id": image_id,
                    "reason": "metadata missing",
                })
                continue

            metadata = ImageMetadata(
                subject=record.subject,
                category=record.category,
                attributes=record.attributes,
                caption=record.caption,
                confidence=record.confidence,
            )
            inputs.append((
                "image",
                image_id,
                prepare_image_input(metadata),
            ))

        for expected in expected_posts:
            record = session.get(
                Post,
                ("demo", expected.id),
            )

            if record is None:
                source_issues.append({
                    "source_type": "post",
                    "source_id": expected.id,
                    "reason": "missing",
                })
                continue

            actual = PostInput(
                id=record.id,
                title=record.title,
                content=record.content,
                required_subject=record.required_subject,
            )

            if actual != expected:
                source_issues.append({
                    "source_type": "post",
                    "source_id": expected.id,
                    "reason": "differs from data/posts.json",
                })
                continue

            inputs.append((
                "post",
                actual.id,
                prepare_post_input(actual),
            ))

    missing_embeddings = []

    for source_type, source_id, prepared in inputs:
        key = EmbeddingCacheKey(
            tenant_id="demo",
            source_type=source_type,
            source_id=source_id,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            task_type=EMBEDDING_TASK_TYPE,
            input_hash=prepared.input_hash,
        )

        if get_cached_embedding(key) is None:
            missing_embeddings.append({
                "source_type": source_type,
                "source_id": source_id,
            })

    return {
        "ready": not source_issues and not missing_embeddings,
        "tenant_id": "demo",
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "expected_images": len(manifest),
        "expected_posts": len(expected_posts),
        "source_issues": source_issues,
        "missing_current_embeddings": missing_embeddings,
    }


def main():
    result = get_demo_readiness()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()