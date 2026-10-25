from typing import Literal

from app.config import get_settings
from app.repositories import embedding_jobs, jobs
from app.repositories.worker_queue import ReadyWorkspaceJob
from app.services.embedding_text import EMBEDDING_TASK_TYPE
from app.workers.embedding_runner import process_embedding_claim
from app.workers.runner import process_claim


DispatchOutcome = Literal[
    "idle",
    "processed",
    "deferred",
    "configuration_mismatch",
]


def dispatch_workspace_job(
    candidate: ReadyWorkspaceJob,
) -> DispatchOutcome:
    settings = get_settings()

    if candidate.kind == "vision":
        jobs.recover_expired_claims(
            candidate.tenant_id,
            candidate.job_id,
        )

        claim = jobs.claim_next_item(
            candidate.tenant_id,
            candidate.job_id,
        )

        if claim is None:
            return "idle"

        succeeded = process_claim(claim, settings)
        return "processed" if succeeded else "deferred"

    if candidate.kind == "embedding":
        summary = embedding_jobs.get_embedding_job_summary(
            candidate.tenant_id,
            candidate.job_id,
        )

        if (
            summary["model"] != settings.embedding_model
            or summary["dimensions"] != settings.embedding_dimensions
            or summary["task_type"] != EMBEDDING_TASK_TYPE
        ):
            return "configuration_mismatch"

        embedding_jobs.recover_expired_embedding_claims(
            candidate.tenant_id,
            candidate.job_id,
        )

        claim = embedding_jobs.claim_next_embedding_item(
            candidate.tenant_id,
            candidate.job_id,
        )

        if claim is None:
            return "idle"

        succeeded = process_embedding_claim(claim)
        return "processed" if succeeded else "deferred"

    raise ValueError("Unsupported worker job kind")