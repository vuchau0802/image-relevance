import json

from app.repositories.jobs import (
    create_processing_job,
    get_job_summary,
)


def main():
    tenant_id = "demo"

    job_id = create_processing_job(
        tenant_id=tenant_id,
        idempotency_key="initial-image-processing",
    )

    summary = get_job_summary(tenant_id, job_id)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()