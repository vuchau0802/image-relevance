from typing import Literal

from pydantic import BaseModel


class EmbeddingJobResponse(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "completed_with_errors",
        "failed",
    ]
    model: str
    dimensions: int
    task_type: str
    total: int
    pending: int
    processing: int
    completed: int
    failed: int