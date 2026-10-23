import re
from dataclasses import dataclass
from uuid import uuid4

from app.config import PROJECT_ROOT
from app.services.upload_validation import validate_image_upload


@dataclass(frozen=True)
class StoredImageUpload:
    image_id: str
    file_path: str
    checksum: str
    width: int
    height: int


def store_image_upload(
    tenant_id: str,
    data: bytes,
) -> StoredImageUpload:
    if (
        not isinstance(tenant_id, str)
        or re.fullmatch(r"ws_[0-9a-f]{32}", tenant_id) is None
    ):
        raise ValueError("Invalid workspace identifier")

    validated = validate_image_upload(data)

    project = PROJECT_ROOT.resolve()
    upload_root = (project / "data" / "uploads").resolve()

    if not upload_root.is_relative_to(project):
        raise ValueError("Upload directory is outside the project")

    workspace_folder = (upload_root / tenant_id).resolve()

    if not workspace_folder.is_relative_to(upload_root):
        raise ValueError("Invalid workspace storage directory")

    workspace_folder.mkdir(parents=True, exist_ok=True)

    image_id = f"img_{uuid4().hex}"
    destination = (
        workspace_folder / f"{image_id}.jpg"
    ).resolve()

    if not destination.is_relative_to(workspace_folder):
        raise ValueError("Invalid upload destination")

    created = False

    try:
        # Exclusive creation prevents overwriting an existing file.
        with destination.open("xb") as output:
            created = True
            output.write(validated.data)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise

    return StoredImageUpload(
        image_id=image_id,
        file_path=destination.relative_to(project).as_posix(),
        checksum=validated.checksum,
        width=validated.width,
        height=validated.height,
    )