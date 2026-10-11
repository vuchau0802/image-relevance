from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Image, ImageMetadataRecord,Job, JobItem
from app.services.classification import ClassificationResult

def create_processing_job(
    tenant_id: str,
    idempotency_key: str,
) -> str:
    if not tenant_id or len(tenant_id) > 50:
        raise ValueError("tenant_id must contain 1–50 characters")

    if not idempotency_key or len(idempotency_key) > 100:
        raise ValueError(
            "idempotency_key must contain 1–100 characters"
        )

    with SessionLocal.begin() as session:
        statement = (
            insert(Job)
            .values(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                status="queued",
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "idempotency_key"]
            )
            .returning(Job.id)
        )

        job_id = session.execute(
            statement
        ).scalar_one_or_none()

        # A repeated request returns the original job.
        if job_id is None:
            return session.execute(
                select(Job.id).where(
                    Job.tenant_id == tenant_id,
                    Job.idempotency_key == idempotency_key,
                )
            ).scalar_one()

        already_queued = exists().where(
            JobItem.tenant_id == Image.tenant_id,
            JobItem.image_id == Image.id,
            JobItem.status.in_(["pending", "processing"]),
        )

        images = session.execute(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.status == "pending",
                ~already_queued,
            )
            .order_by(Image.id)
            .with_for_update(skip_locked=True)
        ).scalars().all()

        if images:
            session.execute(
                insert(JobItem),
                [
                    {
                        "tenant_id": tenant_id,
                        "job_id": job_id,
                        "image_id": image.id,
                        "status": "pending",
                        "attempts": 0,
                        "max_attempts": 3,
                    }
                    for image in images
                ],
            )
        else:
            job = session.get(Job, (tenant_id, job_id))
            job.status = "completed"
            job.finished_at = func.now()

        return job_id


def get_job_summary(tenant_id: str, job_id: str) -> dict:
    with SessionLocal() as session:
        job = session.get(Job, (tenant_id, job_id))

        if job is None:
            raise ValueError("Job not found for this tenant")

        counts = dict(
            session.execute(
                select(JobItem.status, func.count())
                .where(
                    JobItem.tenant_id == tenant_id,
                    JobItem.job_id == job_id,
                )
                .group_by(JobItem.status)
            ).all()
        )

        return {
            "job_id": job.id,
            "status": job.status,
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "needs_review": counts.get("needs_review", 0),
            "failed": counts.get("failed", 0),
        }

@dataclass(frozen=True)
class ClaimedItem:
    tenant_id: str
    job_id: str
    item_id: str
    image_id: str
    file_path: str
    checksum: str
    claim_token: str
    attempt: int


def claim_next_item(
    tenant_id: str,
    job_id: str,
    lease_seconds: int = 120,
) -> ClaimedItem | None:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")

    now = datetime.now(timezone.utc)

    with SessionLocal.begin() as session:
        # Serialize changes to this job while claiming an item.
        job = session.execute(
            select(Job)
            .where(
                Job.tenant_id == tenant_id,
                Job.id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if job is None:
            raise ValueError("Job not found for this tenant")

        if job.status not in {"queued", "running"}:
            return None

        item = session.execute(
            select(JobItem)
            .where(
                JobItem.tenant_id == tenant_id,
                JobItem.job_id == job_id,
                JobItem.status == "pending",
                JobItem.available_at <= now,
                JobItem.attempts < JobItem.max_attempts,
            )
            .order_by(JobItem.image_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()

        if item is None:
            return None

        image = session.execute(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.id == item.image_id,
            )
            .with_for_update()
        ).scalar_one()

        token = str(uuid4())

        item.status = "processing"
        item.attempts += 1
        item.claim_token = token
        item.lease_expires_at = now + timedelta(
            seconds=lease_seconds
        )

        image.status = "processing"
        job.status = "running"

        claimed = ClaimedItem(
            tenant_id=tenant_id,
            job_id=job_id,
            item_id=item.id,
            image_id=item.image_id,
            file_path=image.file_path,
            checksum=image.checksum,
            claim_token=token,
            attempt=item.attempts,
        )

    # The transaction commits before the caller makes an AI request.
    return claimed

class StaleClaimError(Exception):
    pass


def refresh_job_status(session, job: Job) -> None:
    session.flush()

    counts = dict(
        session.execute(
            select(JobItem.status, func.count())
            .where(
                JobItem.tenant_id == job.tenant_id,
                JobItem.job_id == job.id,
            )
            .group_by(JobItem.status)
        ).all()
    )

    active = counts.get("pending", 0) + counts.get("processing", 0)

    if active:
        job.status = "running"
        return

    total = sum(counts.values())
    failed = counts.get("failed", 0)

    if failed and failed == total:
        job.status = "failed"
    elif failed:
        job.status = "completed_with_errors"
    else:
        job.status = "completed"

    job.finished_at = datetime.now(timezone.utc)


def complete_claim(
    claimed: ClaimedItem,
    result: ClassificationResult,
    vision_model: str,
) -> None:
    with SessionLocal.begin() as session:
        job = session.execute(
            select(Job)
            .where(
                Job.tenant_id == claimed.tenant_id,
                Job.id == claimed.job_id,
            )
            .with_for_update()
        ).scalar_one()

        item = session.execute(
            select(JobItem)
            .where(
                JobItem.tenant_id == claimed.tenant_id,
                JobItem.id == claimed.item_id,
                JobItem.job_id == claimed.job_id,
            )
            .with_for_update()
        ).scalar_one()

        now = datetime.now(timezone.utc)

        if (
            item.status != "processing"
            or item.claim_token != claimed.claim_token
            or item.lease_expires_at is None
            or item.lease_expires_at <= now
        ):
            raise StaleClaimError("Job item ownership has expired")

        image = session.execute(
            select(Image)
            .where(
                Image.tenant_id == claimed.tenant_id,
                Image.id == claimed.image_id,
            )
            .with_for_update()
        ).scalar_one()

        if image.checksum != claimed.checksum:
            raise ValueError("Registered image changed during processing")

        statement = insert(ImageMetadataRecord).values(
            tenant_id=claimed.tenant_id,
            image_id=claimed.image_id,
            **result.metadata.model_dump(),
            vision_model=vision_model,
        )

        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "image_id"],
            set_={
                field: getattr(statement.excluded, field)
                for field in (
                    "subject",
                    "category",
                    "attributes",
                    "caption",
                    "confidence",
                    "vision_model",
                )
            },
        )

        session.execute(statement)

        image.status = result.status

        item.status = result.status
        item.finished_at = now
        item.last_error = None
        item.claim_token = None
        item.lease_expires_at = None

        refresh_job_status(session, job)

def reschedule_or_fail(
    session,
    item: JobItem,
    now: datetime,
    retryable: bool,
    error_summary: str,
) -> None:
    image = session.execute(
        select(Image)
        .where(
            Image.tenant_id == item.tenant_id,
            Image.id == item.image_id,
        )
        .with_for_update()
    ).scalar_one()

    item.last_error = error_summary
    item.claim_token = None
    item.lease_expires_at = None

    if retryable and item.attempts < item.max_attempts:
        delay = min(60, 5 * (2 ** max(0, item.attempts - 1)))

        item.status = "pending"
        item.available_at = now + timedelta(seconds=delay)
        item.finished_at = None
        image.status = "pending"
    else:
        item.status = "failed"
        item.finished_at = now
        image.status = "failed"


def fail_claim(
    claimed: ClaimedItem,
    error: Exception,
    retryable: bool,
) -> None:
    with SessionLocal.begin() as session:
        job = session.execute(
            select(Job)
            .where(
                Job.tenant_id == claimed.tenant_id,
                Job.id == claimed.job_id,
            )
            .with_for_update()
        ).scalar_one()

        item = session.execute(
            select(JobItem)
            .where(
                JobItem.tenant_id == claimed.tenant_id,
                JobItem.id == claimed.item_id,
                JobItem.job_id == claimed.job_id,
            )
            .with_for_update()
        ).scalar_one()

        now = datetime.now(timezone.utc)

        if (
            item.status != "processing"
            or item.claim_token != claimed.claim_token
            or item.lease_expires_at is None
            or item.lease_expires_at <= now
        ):
            raise StaleClaimError("Job item ownership has expired")

        # Store only the error type, avoiding raw messages and secrets.
        reschedule_or_fail(
            session,
            item,
            now,
            retryable,
            f"Processing failed: {type(error).__name__}",
        )

        refresh_job_status(session, job)


def recover_expired_claims(
    tenant_id: str,
    job_id: str,
) -> dict:
    recovered = {"requeued": 0, "failed": 0}

    with SessionLocal.begin() as session:
        job = session.execute(
            select(Job)
            .where(
                Job.tenant_id == tenant_id,
                Job.id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if job is None:
            raise ValueError("Job not found for this tenant")

        if job.status not in {"queued", "running"}:
            return recovered

        now = datetime.now(timezone.utc)

        expired_items = session.execute(
            select(JobItem)
            .where(
                JobItem.tenant_id == tenant_id,
                JobItem.job_id == job_id,
                JobItem.status == "processing",
                JobItem.lease_expires_at <= now,
            )
            .order_by(JobItem.image_id)
            .with_for_update()
        ).scalars().all()

        for item in expired_items:
            reschedule_or_fail(
                session,
                item,
                now,
                retryable=True,
                error_summary="Worker lease expired before completion",
            )

            if item.status == "pending":
                recovered["requeued"] += 1
            else:
                recovered["failed"] += 1

        if expired_items:
            refresh_job_status(session, job)

    return recovered