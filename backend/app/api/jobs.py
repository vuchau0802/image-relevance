from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.repositories.jobs import get_job_summary


router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobSummary(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "completed_with_errors",
        "failed",
    ]
    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    completed: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    failed: int = Field(ge=0)


@router.get("/{job_id}", response_model=JobSummary)
def read_job(
    job_id: str,
    tenant_id: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=1,
            max_length=50,
        ),
    ],
):
    try:
        return get_job_summary(
            tenant_id=tenant_id,
            job_id=job_id,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        ) from error