from typing import Literal

from pydantic import BaseModel


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_PIXELS = 20_000_000


class ImageUploadResponse(BaseModel):
    image_id: str
    status: Literal[
        "pending",
        "processing",
        "completed",
        "needs_review",
        "failed",
    ]