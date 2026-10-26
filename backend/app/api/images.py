from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import CurrentWorkspace
from app.database import SessionLocal
from app.models import Image
from app.schemas.image import ImageAttribution
from app.services.image_files import verify_registered_image
from starlette.concurrency import run_in_threadpool

from app.schemas.upload import ImageUploadResponse, MAX_UPLOAD_BYTES
from app.services.upload_validation import InvalidImageUploadError
from app.services.uploads import create_uploaded_image
from app.api.upload_limits import UploadLimitRoute
from app.api.jobs import JobSummary
from app.repositories.jobs import (
    ImageNotProcessableError,
    ProcessingImageNotFoundError,
    create_image_processing_job,
    get_job_summary,
)
from app.repositories.embedding_jobs import (
    EmbeddingImageNotFoundError,
    EmbeddingImageNotReadyError,
    create_image_embedding_job,
    get_embedding_job_summary,
)
from app.schemas.embedding_job import EmbeddingJobResponse
from app.repositories.images import list_images
from app.schemas.image import ImageListResponse

router = APIRouter(prefix="/images", tags=["images"], route_class=UploadLimitRoute)


@router.get("/{image_id}/file", response_class=FileResponse)
def read_image_file(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: CurrentWorkspace,
) -> FileResponse:
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
        path = verify_registered_image(file_path, checksum, tenant_id=tenant_id)
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

@router.get(
    "/{image_id}/attribution",
    response_model=ImageAttribution,
)
def read_image_attribution(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: CurrentWorkspace,
) -> ImageAttribution:
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


@router.post(
    "",
    response_model=ImageUploadResponse,
    status_code=201,
)
async def upload_image(
    tenant_id: CurrentWorkspace,
    file: Annotated[UploadFile, File()],
    creator: Annotated[str, Form(min_length=1, max_length=200)],
) -> ImageUploadResponse:
    try:
        creator = creator.strip()
        if not creator:
            raise HTTPException(
                status_code=422,
                detail="Provide the image creator's name",
            )

        data = await file.read(MAX_UPLOAD_BYTES + 1)

        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The image exceeds the 10 MiB upload limit",
            )

        try:
            return await run_in_threadpool(
                create_uploaded_image,
                tenant_id=tenant_id,
                data=data,
                creator=creator,
            )
        except InvalidImageUploadError as error:
            raise HTTPException(
                status_code=422,
                detail=str(error),
            ) from None
    finally:
        await file.close()

@router.post(
    "/{image_id}/analysis-job",
    response_model=JobSummary,
    status_code=202,
)
def prepare_image_analysis(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: CurrentWorkspace,
) -> JobSummary:
    try:
        job_id = create_image_processing_job(
            tenant_id=tenant_id,
            image_id=image_id,
        )
    except ProcessingImageNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Image not found",
        ) from None
    except ImageNotProcessableError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from None

    return JobSummary.model_validate(
        get_job_summary(
            tenant_id=tenant_id,
            job_id=job_id,
        )
    )

@router.post(
    "/{image_id}/embedding-job",
    response_model=EmbeddingJobResponse,
    status_code=202,
)
def prepare_image_embedding(
    image_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: CurrentWorkspace,
) -> EmbeddingJobResponse:
    try:
        job_id = create_image_embedding_job(
            tenant_id=tenant_id,
            image_id=image_id,
        )
    except EmbeddingImageNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Image not found",
        ) from None
    except EmbeddingImageNotReadyError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from None

    return EmbeddingJobResponse.model_validate(
        get_embedding_job_summary(
            tenant_id=tenant_id,
            job_id=job_id,
        )
    )

@router.get("", response_model=ImageListResponse)
def read_images(
    tenant_id: CurrentWorkspace,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ImageListResponse:
    return list_images(
        tenant_id=tenant_id,
        offset=offset,
        limit=limit,
    )