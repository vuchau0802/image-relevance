from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import FileResponse

from app.database import SessionLocal
from app.models import Image
from app.services.image_files import verify_registered_image
from pydantic import BaseModel


router = APIRouter(prefix="/images", tags=["images"])


@router.get("/{image_id}/file", response_class=FileResponse)
def read_image_file(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=1,
            max_length=50,
        ),
    ],
):
    if not tenant_id.strip() or not image_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Tenant and image identifiers must not be blank",
        )

    with SessionLocal() as session:
        record = session.get(Image, (tenant_id, image_id))

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Image not found",
            )

        file_path = record.file_path
        checksum = record.checksum

    try:
        path = verify_registered_image(file_path, checksum)
    except (ValueError, OSError):
        raise HTTPException(
            status_code=404,
            detail="Image file unavailable",
        ) from None

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

class ImageAttribution(BaseModel):
    image_id: str
    creator: str
    source_url: str
    license_url: str


@router.get(
    "/{image_id}/attribution",
    response_model=ImageAttribution,
)
def read_image_attribution(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=1,
            max_length=50,
        ),
    ],
):
    if not tenant_id.strip() or not image_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Tenant and image identifiers must not be blank",
        )

    with SessionLocal() as session:
        record = session.get(Image, (tenant_id, image_id))

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Image not found",
            )

        return ImageAttribution(
            image_id=record.id,
            creator=record.creator,
            source_url=record.source_url,
            license_url=record.license_url,
        )