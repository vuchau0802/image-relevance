from sqlalchemy import select
from app.database import SessionLocal
from app.models import Image
from app.repositories.metadata import persist_classification
from app.services.classification import ClassificationResult
from app.services.image_files import verify_registered_image
from app.schemas.image import ImageListItem, ImageListResponse

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

def list_images(
    tenant_id: str,
    offset: int = 0,
    limit: int = 50,
) -> ImageListResponse:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 50
    ):
        raise ValueError("Invalid workspace identifier")

    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
    ):
        raise ValueError("offset must be a nonnegative integer")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 100
    ):
        raise ValueError("limit must be between 1 and 100")

    with SessionLocal() as session:
        records = session.scalars(
            select(Image)
            .where(Image.tenant_id == tenant_id)
            .order_by(
                Image.created_at.desc(),
                Image.id.desc(),
            )
            .offset(offset)
            .limit(limit + 1)
        ).all()

        items = [
            ImageListItem(
                image_id=record.id,
                status=record.status,
                creator=record.creator,
                created_at=record.created_at,
            )
            for record in records[:limit]
        ]

    return ImageListResponse(
        items=items,
        next_offset=(
            offset + limit
            if len(records) > limit
            else None
        ),
    )