import re

from sqlalchemy import func, select

from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Image
from app.schemas.upload import ImageUploadResponse
from app.services.upload_storage import StoredImageUpload
from app.config import get_settings

class ImageUploadLimitError(ValueError):
    pass

def register_image_upload(
    tenant_id: str,
    upload: StoredImageUpload,
    creator: str,
    source_url: str = "",
    license_url: str = "",
) -> ImageUploadResponse:
    if re.fullmatch(r"ws_[0-9a-f]{32}", tenant_id) is None:
        raise ValueError("Invalid workspace identifier")

    if re.fullmatch(r"img_[0-9a-f]{32}", upload.image_id) is None:
        raise ValueError("Invalid image identifier")

    expected_path = (
        f"data/uploads/{tenant_id}/{upload.image_id}.jpg"
    )
    if upload.file_path != expected_path:
        raise ValueError("Upload does not belong to this workspace")

    if re.fullmatch(r"[0-9a-f]{64}", upload.checksum) is None:
        raise ValueError("Invalid image checksum")

    if not creator.strip() or len(creator) > 200:
        raise ValueError("Provide a creator name of 1–200 characters")

    with SessionLocal.begin() as session:
        # Serialize upload registration within this workspace.
        # PostgreSQL releases this lock when the transaction ends.
        session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(
                        f"image-upload:{tenant_id}", 0
                    )
                )
            )
        )

        existing = session.execute(
            select(Image.id, Image.status).where(
                Image.tenant_id == tenant_id,
                Image.checksum == upload.checksum,
            )
        ).one_or_none()

        # Duplicates do not consume another image slot.
        if existing is not None:
            return ImageUploadResponse(
                image_id=existing.id,
                status=existing.status,
            )

        limit = get_settings().max_images_per_workspace
        count = session.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.tenant_id == tenant_id)
        )

        if count >= limit:
            raise ImageUploadLimitError(
                f"Your workspace has reached its limit of "
                f"{limit} images. Delete an image before uploading another."
            )

        row = session.execute(
            insert(Image)
            .values(
                tenant_id=tenant_id,
                id=upload.image_id,
                file_path=upload.file_path,
                checksum=upload.checksum,
                creator=creator.strip(),
                source_url=source_url.strip(),
                license_url=license_url.strip(),
                status="pending",
            )
            .on_conflict_do_nothing(
                constraint="uq_images_tenant_checksum",
            )
            .returning(Image.id, Image.status)
        ).one_or_none()

        if row is None:
            row = session.execute(
                select(Image.id, Image.status).where(
                    Image.tenant_id == tenant_id,
                    Image.checksum == upload.checksum,
                )
            ).one()

        result = ImageUploadResponse(
            image_id=row.id,
            status=row.status,
        )


    return result