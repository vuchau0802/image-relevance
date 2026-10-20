from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query

from app.repositories.posts import list_posts
from app.schemas.post import PostListResponse


router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=PostListResponse)
def read_posts(
    tenant_id: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=1,
            max_length=50,
        ),
    ],
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