import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent


def run_module(module, *arguments):
    subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=BACKEND,
        check=True,
    )


def prepare_demo(vision_max_items, embedding_max_items):
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "db"],
        cwd=PROJECT_ROOT,
        check=True,
    )
    run_module("alembic", "upgrade", "head")

    verification = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.download_dataset",
            "--verify-only",
        ],
        cwd=BACKEND,
        check=False,
    )

    if verification.returncode != 0:
        run_module("scripts.download_dataset")

    run_module("scripts.seed_images")
    run_module("scripts.seed_posts")

    # Import application code after initialization.
    from sqlalchemy import select

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import Job, JobItem
    from app.repositories.embedding_jobs import (
        create_embedding_job,
        snapshot_inputs,
    )
    from app.repositories.jobs import create_processing_job
    from scripts.demo_status import get_demo_readiness

    status = get_demo_readiness()

    if status["ready"]:
        print("Demo matching is ready.")
        return True

    image_issues = [
        issue
        for issue in status["source_issues"]
        if issue["source_type"] == "image"
    ]

    if image_issues:
        image_ids = [
            issue["source_id"] for issue in image_issues
        ]

        # Resume an existing active job before creating another.
        with SessionLocal() as session:
            job_id = session.execute(
                select(Job.id)
                .join(
                    JobItem,
                    (Job.tenant_id == JobItem.tenant_id)
                    & (Job.id == JobItem.job_id),
                )
                .where(
                    Job.tenant_id == "demo",
                    Job.status.in_(["queued", "running"]),
                    JobItem.status.in_(
                        ["pending", "processing"]
                    ),
                    JobItem.image_id.in_(image_ids),
                )
                .order_by(Job.created_at, Job.id)
                .limit(1)
            ).scalar_one_or_none()

        if job_id is None:
            fingerprint = hashlib.sha256(
                json.dumps(
                    sorted(image_ids)
                ).encode("utf-8")
            ).hexdigest()

            job_id = create_processing_job(
                tenant_id="demo",
                idempotency_key=(
                    f"demo-vision-{fingerprint}"
                ),
            )

        run_module(
            "app.workers.runner",
            "--job-id",
            job_id,
            "--max-items",
            str(vision_max_items),
        )

        status = get_demo_readiness()

        if status["source_issues"]:
            print(json.dumps(status, indent=2))
            print(
                "Preparation is unfinished. Rerun when retries "
                "are ready or allowance is available. Failed or "
                "needs_review images require investigation."
            )
            return False

    if status["source_issues"]:
        print(json.dumps(status, indent=2))
        return False

    settings = get_settings()

    with SessionLocal() as session:
        snapshots = snapshot_inputs(session, "demo")

    # A source-text or model change creates a new job version.
    fingerprint_data = {
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "task_type": "SEMANTIC_SIMILARITY",
        "sources": sorted(
            (source_type, source_id, prepared.input_hash)
            for source_type, source_id, prepared in snapshots
        ),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_data,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    embedding_job_id = create_embedding_job(
        tenant_id="demo",
        idempotency_key=f"demo-embeddings-{fingerprint}",
    )

    run_module(
        "app.workers.embedding_runner",
        "--job-id",
        embedding_job_id,
        "--max-items",
        str(embedding_max_items),
    )

    status = get_demo_readiness()
    print(json.dumps(status, indent=2))

    if status["ready"]:
        print("Demo matching is ready.")
        return True

    print(
        "Preparation is unfinished. Inspect the embedding job "
        "summary before rerunning. Delayed retries and budget "
        "blocks preserve progress; exhausted items need review."
    )
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vision-max-items",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--embedding-max-items",
        type=int,
        default=100,
    )
    args = parser.parse_args()

    if not 1 <= args.vision_max_items <= 50:
        parser.error("--vision-max-items must be from 1 to 50")

    if not 1 <= args.embedding_max_items <= 1000:
        parser.error(
            "--embedding-max-items must be from 1 to 1000"
        )

    ready = prepare_demo(
        args.vision_max_items,
        args.embedding_max_items,
    )
    raise SystemExit(0 if ready else 2)


if __name__ == "__main__":
    main()