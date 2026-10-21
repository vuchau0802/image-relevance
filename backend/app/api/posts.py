from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CurrentWorkspace
from app.repositories.posts import create_post, list_posts
from app.schemas.post import PostCreate, PostInput, PostListResponse


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