from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Path,
    Query,
)
from pydantic import BaseModel, Field

from app.services.ranking import (
    MissingPostEmbeddingError,
    PostNotFoundError,
    rank_post_images,
)


router = APIRouter(prefix="/posts", tags=["recommendations"])


class RankedImage(BaseModel):
    image_id: str
    subject: str
    caption: str
    similarity: float = Field(
        ge=-1,
        le=1,
        allow_inf_nan=False,
    )


class RankingResponse(BaseModel):
    post_id: str
    status: Literal[
        "unsupported_subject",
        "no_confident_match",
        "incomplete",
        "matched",
    ]
    reason: str
    required_subject: str
    model: str
    dimensions: int = Field(ge=1, le=3072)
    candidates_scored: int = Field(ge=0)
    subject_compatible_candidates: int = Field(ge=0)
    subject_rejected_count: int = Field(ge=0)
    missing_current_embeddings: list[str]
    results: list[RankedImage]


@router.get(
    "/{post_id}/images",
    response_model=RankingResponse,
)
def read_ranked_images(
    post_id: Annotated[
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
    top: Annotated[int, Query(ge=1, le=50)] = 5,
):
    if not tenant_id.strip() or not post_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Tenant and post identifiers must not be blank",
        )

    try:
        return rank_post_images(
            tenant_id=tenant_id,
            post_id=post_id,
            top=top,
        )
    except PostNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Post not found",
        ) from error
    except MissingPostEmbeddingError as error:
        raise HTTPException(
            status_code=409,
            detail="Current post embedding is unavailable",
        ) from error