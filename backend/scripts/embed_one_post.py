import argparse
import json
import math

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Post
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.post import PostInput
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    prepare_post_input,
)
from app.services.embeddings import get_or_create_embedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--post-id", default="post_001")
    args = parser.parse_args()

    settings = get_settings()

    with SessionLocal() as session:
        record = session.execute(
            select(Post).where(
                Post.tenant_id == args.tenant_id,
                Post.id == args.post_id,
            )
        ).scalar_one_or_none()

        if record is None:
            raise SystemExit(
                "Post not found for this tenant."
            )

        post = PostInput(
            id=record.id,
            title=record.title,
            content=record.content,
            required_subject=record.required_subject,
        )

    prepared = prepare_post_input(post)

    key = EmbeddingCacheKey(
        tenant_id=args.tenant_id,
        source_type="post",
        source_id=args.post_id,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        task_type=EMBEDDING_TASK_TYPE,
        input_hash=prepared.input_hash,
    )

    result = get_or_create_embedding(key, prepared)

    print(json.dumps(
        {
            "post_id": args.post_id,
            "model": key.model,
            "dimensions": len(result.vector),
            "vector_norm": math.hypot(*result.vector),
            "cache_hit": result.cache_hit,
            "call_id": result.call_id,
            "input_hash": key.input_hash,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()