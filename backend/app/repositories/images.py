from sqlalchemy import select
from app.database import SessionLocal
from app.models import Image
from app.repositories.metadata import persist_classification
from app.services.classification import ClassificationResult
from app.services.image_files import verify_registered_image


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

        verify_registered_image(image.file_path, image.checksum, tenant_id=tenant_id)
        persist_classification(session, image, result, vision_model)
