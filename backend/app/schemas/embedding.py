from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingCacheKey(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    tenant_id: str = Field(min_length=1, max_length=50)
    source_type: Literal["image", "post"]
    source_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)

    dimensions: int = Field(
        strict=True,
        ge=1,
        le=3072,
    )

    task_type: Literal["SEMANTIC_SIMILARITY"] = (
        "SEMANTIC_SIMILARITY"
    )

    input_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )