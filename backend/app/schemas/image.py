from typing import Annotated, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ImageMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    subject: str = Field(min_length=1, max_length=200)
    category: Literal["animal", "vehicle", "food", "landscape"]
    attributes: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=20,
    )
    caption: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class ImageAttribution(BaseModel):
    image_id: str
    creator: str
    source_url: str
    license_url: str

class ImageListItem(BaseModel):
    image_id: str
    embedding_ready: bool = False
    status: Literal[
        "pending",
        "processing",
        "completed",
        "needs_review",
        "failed",
    ]
    creator: str
    created_at: datetime


class ImageListResponse(BaseModel):
    items: list[ImageListItem]
    next_offset: int | None