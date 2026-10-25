from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, exists, func, or_, select, tuple_

from app.database import SessionLocal
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    Job,
    JobItem,
    Workspace,
)


@dataclass(frozen=True)
class ReadyWorkspaceJob:
    kind: Literal["vision", "embedding"]
    tenant_id: str
    job_id: str


def list_ready_workspace_jobs(
    limit: int = 20,
    exclude: set[ReadyWorkspaceJob] | None = None,
) -> list[ReadyWorkspaceJob]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 1000
    ):
        raise ValueError("limit must be between 1 and 1000")

    candidates = []

    with SessionLocal() as session:
        for kind, job_model, item_model in [
            ("vision", Job, JobItem),
            ("embedding", EmbeddingJob, EmbeddingJobItem),
        ]:
            ready_item = exists().where(
                item_model.tenant_id == job_model.tenant_id,
                item_model.job_id == job_model.id,
                or_(
                    and_(
                        item_model.status == "pending",
                        item_model.available_at <= func.now(),
                    ),
                    and_(
                        item_model.status == "processing",
                        item_model.lease_expires_at <= func.now(),
                    ),
                ),
            )

            excluded_keys = [
                (candidate.tenant_id, candidate.job_id)
                for candidate in (exclude or set())
                if candidate.kind == kind
            ]

            rows = session.execute(
                select(
                    job_model.tenant_id,
                    job_model.id,
                    job_model.created_at,
                )
                .join(
                    Workspace,
                    Workspace.id == job_model.tenant_id,
                )
                .where(
                    job_model.status.in_(["queued", "running"]),
                    ready_item,
                    ~tuple_(
                        job_model.tenant_id,
                        job_model.id,
                    ).in_(excluded_keys),
                )
                .order_by(
                    job_model.created_at,
                    job_model.tenant_id,
                    job_model.id,
                )
                .limit(limit)
            ).all()

            for row in rows:
                candidates.append(
                    (
                        row.created_at,
                        kind,
                        row.tenant_id,
                        row.id,
                    )
                )

    candidates.sort()

    return [
        ReadyWorkspaceJob(
            kind=kind,
            tenant_id=tenant_id,
            job_id=job_id,
        )
        for _, kind, tenant_id, job_id in candidates[:limit]
    ]