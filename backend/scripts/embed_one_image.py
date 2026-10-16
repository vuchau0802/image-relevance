import argparse
import json
import math

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Image, ImageMetadataRecord
from app.schemas.embedding import EmbeddingCacheKey
from app.schemas.image import ImageMetadata
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    prepare_image_input,
)
from app.services.embeddings import get_or_create_embedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--image-id", default="img_001")
    args = parser.parse_args()

    settings = get_settings()

    with SessionLocal() as session:
        record = session.execute(
            select(ImageMetadataRecord)
            .join(
                Image,
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
                Image.tenant_id == args.tenant_id,
                Image.id == args.image_id,
                Image.status == "completed",
            )
        ).scalar_one_or_none()

        if record is None:
            raise SystemExit(
                "Completed image with metadata not found "
                "for this tenant."
            )

        metadata = ImageMetadata(
            subject=record.subject,
            category=record.category,
            attributes=record.attributes,
            caption=record.caption,
            confidence=record.confidence,
        )

    # The database session closes before the remote request.
    prepared = prepare_image_input(metadata)

    key = EmbeddingCacheKey(
        tenant_id=args.tenant_id,
        source_type="image",
        source_id=args.image_id,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        task_type=EMBEDDING_TASK_TYPE,
        input_hash=prepared.input_hash,
    )

    result = get_or_create_embedding(key, prepared)

    print(json.dumps(
        {
            "image_id": args.image_id,
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