import hashlib

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image, ImageMetadataRecord
from app.services.classification import ClassificationResult


def save_classification(
    tenant_id: str,
    image_id: str,
    result: ClassificationResult,
    vision_model: str,
) -> None:
    with SessionLocal.begin() as session:
        image = session.execute(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.id == image_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if image is None:
            raise ValueError(
                f"Image not registered for this tenant: {image_id}"
            )

        image_path = PROJECT_ROOT / image.file_path
        current_checksum = hashlib.sha256(
            image_path.read_bytes()
        ).hexdigest()

        if current_checksum != image.checksum:
            raise ValueError(
                f"Image file changed since registration: {image_id}"
            )

        values = {
            "tenant_id": tenant_id,
            "image_id": image_id,
            **result.metadata.model_dump(),
            "vision_model": vision_model,
        }

        statement = insert(ImageMetadataRecord).values(**values)

        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "image_id"],
            set_={
                field: getattr(statement.excluded, field)
                for field in (
                    "subject",
                    "category",
                    "attributes",
                    "caption",
                    "confidence",
                    "vision_model",
                )
            },
        )

        session.execute(statement)
        image.status = result.status