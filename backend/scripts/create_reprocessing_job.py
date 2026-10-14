import json

from app.repositories.jobs import create_processing_job, get_job_summary


def main():
    tenant_id = "demo"
    job_id = create_processing_job(
        tenant_id=tenant_id,
        idempotency_key="failed-image-reprocessing-v1",
        source_status="failed",
    )
    print(json.dumps(get_job_summary(tenant_id, job_id), indent=2))


if __name__ == "__main__":
    main()
