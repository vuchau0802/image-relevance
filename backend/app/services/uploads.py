import logging

from app.repositories.uploads import ImageUploadLimitError, register_image_upload
from app.schemas.upload import ImageUploadResponse
from app.services import upload_storage
from app.services.upload_storage import StoredImageUpload


logger = logging.getLogger(__name__)


def remove_duplicate_file(
    tenant_id: str,
    upload: StoredImageUpload,
) -> None:
    project = upload_storage.PROJECT_ROOT.resolve()
    workspace = (
        project / "data" / "uploads" / tenant_id
    ).resolve()
    path = (project / upload.file_path).resolve()

    if not workspace.is_relative_to(project):
        raise ValueError("Invalid workspace directory")

    if (
        path.parent != workspace
        or path.name != f"{upload.image_id}.jpg"
    ):
        raise ValueError("Invalid duplicate file path")

    path.unlink(missing_ok=True)


def create_uploaded_image(
    tenant_id: str,
    data: bytes,
    creator: str,
    source_url: str = "",
    license_url: str = "",
) -> ImageUploadResponse:
    # Reject invalid attribution before writing a file.
    if not creator.strip() or len(creator) > 200:
        raise ValueError(
            "Provide a creator name of 1–200 characters"
        )

    stored = upload_storage.store_image_upload(
        tenant_id=tenant_id,
        data=data,
    )

    try:
        result = register_image_upload(
            tenant_id=tenant_id,
            upload=stored,
            creator=creator,
            source_url=source_url,
            license_url=license_url,
        )
    except ImageUploadLimitError:
        # Registration rejected the upload and rolled back.
        # Remove only the new candidate file.
        try:
            remove_duplicate_file(tenant_id, stored)
        except OSError:
            logger.exception(
                "Could not remove quota-rejected upload %s",
                stored.image_id,
            )
        raise

    if result.image_id != stored.image_id:
        # Registration committed and returned an existing image.
        # Only the newly written duplicate file is removed.
        try:
            remove_duplicate_file(tenant_id, stored)
        except OSError:
            logger.exception(
                "Could not remove duplicate upload %s",
                stored.image_id,
            )

    return result