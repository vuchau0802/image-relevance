from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CurrentWorkspace
from app.repositories.posts import create_post, list_posts
from app.schemas.post import PostCreate, PostInput, PostListResponse
from app.repositories.embedding_jobs import (
    EmbeddingPostNotFoundError,
    create_post_embedding_job,
    get_embedding_job_summary,
)
from app.schemas.embedding_job import EmbeddingJobResponse

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=PostListResponse)
def read_posts(
    tenant_id: CurrentWorkspace,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PostListResponse:
    if not tenant_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Tenant identifier must not be blank",
        )

    return list_posts(
        tenant_id=tenant_id,
        offset=offset,
        limit=limit,
    )

@router.post(
    "",
    response_model=PostInput,
    status_code=201,
)
def write_post(
    payload: PostCreate,
    tenant_id: CurrentWorkspace,
) -> PostInput:
    return create_post(
        tenant_id=tenant_id,
        payload=payload,
    )

@router.post(
    "/{post_id}/embedding-job",
    response_model=EmbeddingJobResponse,
    status_code=202,
)
def prepare_post_embedding(
    post_id: str,
    tenant_id: CurrentWorkspace,
) -> EmbeddingJobResponse:
    try:
        job_id = create_post_embedding_job(
            tenant_id=tenant_id,
            post_id=post_id,
        )
    except EmbeddingPostNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Post not found",
        ) from None

    return EmbeddingJobResponse.model_validate(
        get_embedding_job_summary(
            tenant_id=tenant_id,
            job_id=job_id,
        )
    )