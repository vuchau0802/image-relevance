from uuid import uuid4
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from app.schemas.embedding import EmbeddingCacheKey
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    EmbeddingJob,
    EmbeddingJobItem,
    Image,
    ImageMetadataRecord,
    ImageEmbedding,
    PostEmbedding,
    Post,
)
from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput
from app.services.embedding_text import (
    EMBEDDING_TASK_TYPE,
    PreparedEmbeddingInput,
    prepare_image_input,
    prepare_post_input,
)


def snapshot_inputs(session, tenant_id):
    snapshots = []

    images = session.execute(
        select(Image.id, ImageMetadataRecord)
        .join(
            ImageMetadataRecord,
            (
                Image.tenant_id
                == ImageMetadataRecord.tenant_id
            )
            & (
                Image.id
                == ImageMetadataRecord.image_id
            ),
        )
        .where(
            Image.tenant_id == tenant_id,
            Image.status == "completed",
        )
        .order_by(Image.id)
        .with_for_update(of=Image)
    ).all()

    for image_id, record in images:
        metadata = ImageMetadata(
            subject=record.subject,
            category=record.category,
            attributes=record.attributes,
            caption=record.caption,
            confidence=record.confidence,
        )

        snapshots.append((
            "image",
            image_id,
            prepare_image_input(metadata),
        ))

    posts = session.scalars(
        select(Post)
        .where(Post.tenant_id == tenant_id)
        .order_by(Post.id)
        .with_for_update()
    ).all()

    for record in posts:
        post = PostInput(
            id=record.id,
            title=record.title,
            content=record.content,
            required_subject=record.required_subject,
        )

        snapshots.append((
            "post",
            record.id,
            prepare_post_input(post),
        ))

    return snapshots


def create_embedding_job(
    tenant_id: str,
    idempotency_key: str,
) -> str:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 50
    ):
        raise ValueError("Invalid tenant_id")

    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 200
    ):
        raise ValueError("Invalid idempotency_key")

    settings = get_settings()
    proposed_id = str(uuid4())

    with SessionLocal.begin() as session:
        inserted_id = session.execute(
            insert(EmbeddingJob)
            .values(
                tenant_id=tenant_id,
                id=proposed_id,
                idempotency_key=idempotency_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                task_type=EMBEDDING_TASK_TYPE,
                status="queued",
            )
            .on_conflict_do_nothing(
                constraint="uq_embedding_jobs_tenant_idempotency",
            )
            .returning(EmbeddingJob.id)
        ).scalar_one_or_none()

        if inserted_id is None:
            existing = session.execute(
                select(EmbeddingJob).where(
                    EmbeddingJob.tenant_id == tenant_id,
                    EmbeddingJob.idempotency_key
                    == idempotency_key,
                )
            ).scalar_one()

            if (
                existing.model != settings.embedding_model
                or existing.dimensions
                != settings.embedding_dimensions
                or existing.task_type != EMBEDDING_TASK_TYPE
            ):
                raise ValueError(
                    "Idempotency key already belongs to a "
                    "different embedding configuration"
                )

            return existing.id

        snapshots = snapshot_inputs(session, tenant_id)

        for source_type, source_id, prepared in snapshots:
            session.add(EmbeddingJobItem(
                tenant_id=tenant_id,
                id=str(uuid4()),
                job_id=inserted_id,
                source_type=source_type,
                source_id=source_id,
                input_text=prepared.text,
                input_hash=prepared.input_hash,
                status="pending",
                attempts=0,
                max_attempts=3,
            ))

        if not snapshots:
            job = session.get(
                EmbeddingJob,
                (tenant_id, inserted_id),
            )
            job.status = "completed"
            job.finished_at = func.now()

    return inserted_id

def get_embedding_job_summary(
    tenant_id: str,
    job_id: str,
) -> dict:
    with SessionLocal() as session:
        job = session.get(
            EmbeddingJob,
            (tenant_id, job_id),
        )

        if job is None:
            raise ValueError(
                "Embedding job not found for this tenant"
            )

        rows = session.execute(
            select(
                EmbeddingJobItem.status,
                func.count(),
            )
            .where(
                EmbeddingJobItem.tenant_id == tenant_id,
                EmbeddingJobItem.job_id == job_id,
            )
            .group_by(EmbeddingJobItem.status)
        ).all()

        counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
        }
        counts.update(dict(rows))

        return {
            "job_id": job.id,
            "status": job.status,
            "model": job.model,
            "dimensions": job.dimensions,
            "task_type": job.task_type,
            "total": sum(counts.values()),
            **counts,
        }

@dataclass(frozen=True)
class EmbeddingClaim:
    tenant_id: str
    job_id: str
    item_id: str
    claim_token: str
    attempt: int
    key: EmbeddingCacheKey
    prepared: PreparedEmbeddingInput


def claim_next_embedding_item(
    tenant_id: str,
    job_id: str,
    *,
    lease_seconds: int = 180,
) -> EmbeddingClaim | None:
    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or not 30 <= lease_seconds <= 3600
    ):
        raise ValueError(
            "lease_seconds must be an integer from 30 to 3600"
        )

    with SessionLocal.begin() as session:
        # All job mutations will lock the parent before its items.
        job = session.execute(
            select(EmbeddingJob)
            .where(
                EmbeddingJob.tenant_id == tenant_id,
                EmbeddingJob.id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if job is None:
            raise ValueError(
                "Embedding job not found for this tenant"
            )

        if job.status not in {"queued", "running"}:
            return None

        now = session.scalar(select(func.clock_timestamp()))

        item = session.execute(
            select(EmbeddingJobItem)
            .where(
                EmbeddingJobItem.tenant_id == tenant_id,
                EmbeddingJobItem.job_id == job_id,
                EmbeddingJobItem.status == "pending",
                EmbeddingJobItem.available_at <= now,
                EmbeddingJobItem.attempts
                < EmbeddingJobItem.max_attempts,
            )
            .order_by(
                EmbeddingJobItem.created_at,
                EmbeddingJobItem.source_type,
                EmbeddingJobItem.source_id,
                EmbeddingJobItem.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()

        if item is None:
            return None

        token = str(uuid4())

        item.status = "processing"
        item.attempts += 1
        item.claim_token = token
        item.lease_expires_at = now + timedelta(
            seconds=lease_seconds
        )
        item.finished_at = None

        job.status = "running"
        job.finished_at = None

        claim = EmbeddingClaim(
            tenant_id=tenant_id,
            job_id=job_id,
            item_id=item.id,
            claim_token=token,
            attempt=item.attempts,
            key=EmbeddingCacheKey(
                tenant_id=tenant_id,
                source_type=item.source_type,
                source_id=item.source_id,
                model=job.model,
                dimensions=job.dimensions,
                task_type=job.task_type,
                input_hash=item.input_hash,
            ),
            prepared=PreparedEmbeddingInput(
                text=item.input_text,
                input_hash=item.input_hash,
            ),
        )

    return claim

class StaleEmbeddingClaimError(ValueError):
    pass


def _lock_embedding_claim(session, claim):
    job = session.execute(
        select(EmbeddingJob)
        .where(
            EmbeddingJob.tenant_id == claim.tenant_id,
            EmbeddingJob.id == claim.job_id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if job is None:
        raise StaleEmbeddingClaimError("Embedding job is missing")

    item = session.execute(
        select(EmbeddingJobItem)
        .where(
            EmbeddingJobItem.tenant_id == claim.tenant_id,
            EmbeddingJobItem.job_id == claim.job_id,
            EmbeddingJobItem.id == claim.item_id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    now = session.scalar(select(func.clock_timestamp()))

    if (
        item is None
        or item.status != "processing"
        or item.claim_token != claim.claim_token
        or item.attempts != claim.attempt
        or item.lease_expires_at is None
        or item.lease_expires_at <= now
    ):
        raise StaleEmbeddingClaimError(
            "Embedding claim is expired or no longer owned"
        )

    if (
        claim.key.tenant_id != claim.tenant_id
        or claim.key.source_type != item.source_type
        or claim.key.source_id != item.source_id
        or claim.key.input_hash != item.input_hash
        or claim.key.model != job.model
        or claim.key.dimensions != job.dimensions
        or claim.key.task_type != job.task_type
        or claim.prepared.text != item.input_text
        or claim.prepared.input_hash != item.input_hash
    ):
        raise StaleEmbeddingClaimError(
            "Embedding claim does not match its stored snapshot"
        )

    return job, item, now


def _refresh_embedding_job(session, job, now):
    # SessionLocal has autoflush=False. Persist item changes
    # before counting their statuses.
    session.flush()

    counts = dict(session.execute(
        select(
            EmbeddingJobItem.status,
            func.count(),
        )
        .where(
            EmbeddingJobItem.tenant_id == job.tenant_id,
            EmbeddingJobItem.job_id == job.id,
        )
        .group_by(EmbeddingJobItem.status)
    ).all())

    unfinished = (
        counts.get("pending", 0)
        + counts.get("processing", 0)
    )

    if unfinished:
        if job.status != "queued":
            job.status = "running"
        job.finished_at = None
    else:
        failed = counts.get("failed", 0)
        completed = counts.get("completed", 0)

        if failed and completed:
            job.status = "completed_with_errors"
        elif failed:
            job.status = "failed"
        else:
            job.status = "completed"

        job.finished_at = job.finished_at or now

def complete_embedding_claim(
    claim: EmbeddingClaim,
    *,
    cache_hit: bool,
) -> None:
    if not isinstance(cache_hit, bool):
        raise ValueError("cache_hit must be a boolean")

    with SessionLocal.begin() as session:
        job, item, now = _lock_embedding_claim(
            session, claim
        )

        table = (
            ImageEmbedding
            if item.source_type == "image"
            else PostEmbedding
        )

        cached = session.get(
            table,
            (
                claim.tenant_id,
                item.source_id,
                job.model,
                job.dimensions,
                job.task_type,
                item.input_hash,
            ),
        )

        if cached is None:
            raise ValueError(
                "Cannot complete an item without its cached embedding"
            )

        item.status = "completed"
        item.cache_hit = cache_hit
        item.claim_token = None
        item.lease_expires_at = None
        item.last_error = None
        item.finished_at = now

        _refresh_embedding_job(session, job, now)

def refresh_embedding_job_status(
    tenant_id: str,
    job_id: str,
) -> None:
    with SessionLocal.begin() as session:
        job = session.execute(
            select(EmbeddingJob)
            .where(
                EmbeddingJob.tenant_id == tenant_id,
                EmbeddingJob.id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if job is None:
            raise ValueError(
                "Embedding job not found for this tenant"
            )

        now = session.scalar(select(func.clock_timestamp()))
        _refresh_embedding_job(session, job, now)

def _finish_failed_embedding_attempt(
    item,
    now,
    *,
    retryable: bool,
    error_message: str,
) -> str:
    item.claim_token = None
    item.lease_expires_at = None
    item.last_error = error_message
    item.cache_hit = None

    if retryable and item.attempts < item.max_attempts:
        delay_seconds = min(
            60,
            5 * (2 ** min(max(item.attempts - 1, 0), 4)),
        )

        item.status = "pending"
        item.available_at = now + timedelta(
            seconds=delay_seconds
        )
        item.finished_at = None
    else:
        item.status = "failed"
        item.finished_at = now

    return item.status

def fail_embedding_claim(
    claim: EmbeddingClaim,
    *,
    retryable: bool,
    error_type: str,
) -> str:
    if not isinstance(retryable, bool):
        raise ValueError("retryable must be a boolean")

    if (
        not isinstance(error_type, str)
        or not error_type.isidentifier()
        or len(error_type) > 100
    ):
        raise ValueError(
            "error_type must be an exception class name"
        )

    with SessionLocal.begin() as session:
        job, item, now = _lock_embedding_claim(
            session, claim
        )

        status = _finish_failed_embedding_attempt(
            item,
            now,
            retryable=retryable,
            error_message=f"Processing failed: {error_type}",
        )

        _refresh_embedding_job(session, job, now)

    return status

def recover_expired_embedding_claims(
    tenant_id: str,
    job_id: str,
) -> dict:
    recovered = {
        "requeued": 0,
        "failed": 0,
    }

    with SessionLocal.begin() as session:
        # Keep the same parent-before-item lock order
        # used by claiming and completion.
        job = session.execute(
            select(EmbeddingJob)
            .where(
                EmbeddingJob.tenant_id == tenant_id,
                EmbeddingJob.id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if job is None:
            raise ValueError(
                "Embedding job not found for this tenant"
            )

        now = session.scalar(select(func.clock_timestamp()))

        items = session.scalars(
            select(EmbeddingJobItem)
            .where(
                EmbeddingJobItem.tenant_id == tenant_id,
                EmbeddingJobItem.job_id == job_id,
                EmbeddingJobItem.status == "processing",
                EmbeddingJobItem.lease_expires_at <= now,
            )
            .order_by(EmbeddingJobItem.id)
            .with_for_update()
        ).all()

        for item in items:
            status = _finish_failed_embedding_attempt(
                item,
                now,
                retryable=True,
                error_message=(
                    "Worker lease expired before completion"
                ),
            )

            if status == "pending":
                recovered["requeued"] += 1
            else:
                recovered["failed"] += 1

        _refresh_embedding_job(session, job, now)

    return recovered

def release_unstarted_embedding_claim(
    claim: EmbeddingClaim,
) -> None:
    """Release ownership when no provider request was started."""
    with SessionLocal.begin() as session:
        job, item, now = _lock_embedding_claim(
            session, claim
        )

        item.status = "pending"
        item.attempts -= 1
        item.claim_token = None
        item.lease_expires_at = None
        item.finished_at = None
        item.available_at = now

        # Preserve last_error from an earlier genuine attempt.
        _refresh_embedding_job(session, job, now)

class EmbeddingPostNotFoundError(LookupError):
    pass


def create_post_embedding_job(
    tenant_id: str,
    post_id: str,
) -> str:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 50
    ):
        raise ValueError("Invalid tenant_id")

    if (
        not isinstance(post_id, str)
        or not post_id.strip()
        or len(post_id) > 50
    ):
        raise ValueError("Invalid post_id")

    settings = get_settings()

    with SessionLocal.begin() as session:
        record = session.get(Post, (tenant_id, post_id), with_for_update=True)

        if record is None:
            raise EmbeddingPostNotFoundError(
                "Post not found for this workspace"
            )

        prepared = prepare_post_input(
            PostInput(
                id=record.id,
                title=record.title,
                content=record.content,
                required_subject=record.required_subject,
            )
        )

        identity = json.dumps(
            {
                "post_id": post_id,
                "input_hash": prepared.input_hash,
                "model": settings.embedding_model,
                "dimensions": settings.embedding_dimensions,
                "task_type": EMBEDDING_TASK_TYPE,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()
        idempotency_key = f"post-embedding-v1:{digest}"

        inserted_id = session.execute(
            insert(EmbeddingJob)
            .values(
                tenant_id=tenant_id,
                id=str(uuid4()),
                idempotency_key=idempotency_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                task_type=EMBEDDING_TASK_TYPE,
                status="queued",
            )
            .on_conflict_do_nothing(
                constraint="uq_embedding_jobs_tenant_idempotency",
            )
            .returning(EmbeddingJob.id)
        ).scalar_one_or_none()

        if inserted_id is None:
            return session.scalar(
                select(EmbeddingJob.id).where(
                    EmbeddingJob.tenant_id == tenant_id,
                    EmbeddingJob.idempotency_key == idempotency_key,
                )
            )

        session.add(
            EmbeddingJobItem(
                tenant_id=tenant_id,
                id=str(uuid4()),
                job_id=inserted_id,
                source_type="post",
                source_id=post_id,
                input_text=prepared.text,
                input_hash=prepared.input_hash,
                status="pending",
                attempts=0,
                max_attempts=3,
            )
        )

    return inserted_id

class EmbeddingImageNotFoundError(LookupError):
    pass


class EmbeddingImageNotReadyError(ValueError):
    pass


def create_image_embedding_job(
    tenant_id: str,
    image_id: str,
) -> str:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 50
    ):
        raise ValueError("Invalid tenant_id")

    if (
        not isinstance(image_id, str)
        or not image_id.strip()
        or len(image_id) > 50
    ):
        raise ValueError("Invalid image_id")

    settings = get_settings()

    with SessionLocal.begin() as session:
        image = session.get(
            Image,
            (tenant_id, image_id),
            with_for_update=True,
        )

        if image is None:
            raise EmbeddingImageNotFoundError(
                "Image not found for this workspace"
            )

        if image.status != "completed":
            raise EmbeddingImageNotReadyError(
                "Image analysis must complete before embedding preparation"
            )

        record = session.get(
            ImageMetadataRecord,
            (tenant_id, image_id),
        )

        if record is None:
            raise EmbeddingImageNotReadyError(
                "Completed image metadata is missing"
            )

        prepared = prepare_image_input(
            ImageMetadata(
                subject=record.subject,
                category=record.category,
                attributes=record.attributes,
                caption=record.caption,
                confidence=record.confidence,
            )
        )

        identity = json.dumps(
            {
                "image_id": image_id,
                "input_hash": prepared.input_hash,
                "model": settings.embedding_model,
                "dimensions": settings.embedding_dimensions,
                "task_type": EMBEDDING_TASK_TYPE,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()
        idempotency_key = f"image-embedding-v1:{digest}"

        inserted_id = session.execute(
            insert(EmbeddingJob)
            .values(
                tenant_id=tenant_id,
                id=str(uuid4()),
                idempotency_key=idempotency_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                task_type=EMBEDDING_TASK_TYPE,
                status="queued",
            )
            .on_conflict_do_nothing(
                constraint="uq_embedding_jobs_tenant_idempotency",
            )
            .returning(EmbeddingJob.id)
        ).scalar_one_or_none()

        if inserted_id is None:
            return session.execute(
                select(EmbeddingJob.id).where(
                    EmbeddingJob.tenant_id == tenant_id,
                    EmbeddingJob.idempotency_key == idempotency_key,
                )
            ).scalar_one()

        session.add(
            EmbeddingJobItem(
                tenant_id=tenant_id,
                id=str(uuid4()),
                job_id=inserted_id,
                source_type="image",
                source_id=image_id,
                input_text=prepared.text,
                input_hash=prepared.input_hash,
                status="pending",
                attempts=0,
                max_attempts=3,
            )
        )

    return inserted_id