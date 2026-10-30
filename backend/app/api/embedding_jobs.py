from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path

from app.api.dependencies import CurrentWorkspace
from app.repositories.embedding_jobs import (
    EmbeddingRetryNotAllowedError,
    EmbeddingRetrySourceNotFoundError,
    get_embedding_job_summary,
    retry_embedding_job,
)
from app.schemas.embedding_job import EmbeddingJobResponse


router = APIRouter(
    prefix="/embedding-jobs",
    tags=["embedding jobs"],
)


@router.get(
    "/{job_id}",
    response_model=EmbeddingJobResponse,
)
def read_embedding_job(
    job_id: str,
    tenant_id: CurrentWorkspace,
) -> EmbeddingJobResponse:
    try:
        summary = get_embedding_job_summary(
            tenant_id=tenant_id,
            job_id=job_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Embedding job not found",
        ) from None

    return EmbeddingJobResponse.model_validate(summary)

@router.post(
    "/{failed_job_id}/retry/{source_type}/{source_id}",
    response_model=EmbeddingJobResponse,
    status_code=202,
)
def retry_embedding_preparation(
    failed_job_id: UUID,
    source_type: Literal["image", "post"],
    source_id: Annotated[
        str,
        Path(min_length=1, max_length=50),
    ],
    tenant_id: CurrentWorkspace,
) -> EmbeddingJobResponse:
    try:
        job_id = retry_embedding_job(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            failed_job_id=str(failed_job_id),
        )
    except EmbeddingRetrySourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Embedding source not found",
        ) from None
    except EmbeddingRetryNotAllowedError as error:
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