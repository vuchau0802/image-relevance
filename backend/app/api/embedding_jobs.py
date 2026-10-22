from fastapi import APIRouter, HTTPException

from app.api.dependencies import CurrentWorkspace
from app.repositories.embedding_jobs import get_embedding_job_summary
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