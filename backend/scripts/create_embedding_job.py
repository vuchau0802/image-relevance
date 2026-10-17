import argparse
import json

from app.repositories.embedding_jobs import (
    create_embedding_job,
    get_embedding_job_summary,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument(
        "--idempotency-key",
        default="initial-embedding-processing-v1",
    )
    args = parser.parse_args()

    job_id = create_embedding_job(
        tenant_id=args.tenant_id,
        idempotency_key=args.idempotency_key,
    )

    summary = get_embedding_job_summary(
        tenant_id=args.tenant_id,
        job_id=job_id,
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()