from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.main import app


client = TestClient(app)


def test_job_status_uses_requested_tenant(monkeypatch):
    calls = []

    def fake_summary(tenant_id, job_id):
        calls.append((tenant_id, job_id))
        return {
            "job_id": job_id,
            "status": "running",
            "total": 3,
            "pending": 2,
            "processing": 0,
            "completed": 1,
            "needs_review": 0,
            "failed": 0,
        }

    monkeypatch.setattr(jobs_api, "get_job_summary", fake_summary)

    response = client.get(
        "/jobs/test-job",
        headers={"X-Tenant-ID": "tenant-a"},
    )

    assert response.status_code == 200
    assert response.json()["pending"] == 2
    assert calls == [("tenant-a", "test-job")]


def test_missing_tenant_header_is_rejected(monkeypatch):
    def unexpected_lookup(**kwargs):
        raise AssertionError("Database lookup should not occur")

    monkeypatch.setattr(
        jobs_api,
        "get_job_summary",
        unexpected_lookup,
    )

    response = client.get("/jobs/test-job")

    assert response.status_code == 422


def test_job_not_found_returns_404(monkeypatch):
    def missing_job(tenant_id, job_id):
        raise ValueError("Job not found for this tenant")

    monkeypatch.setattr(jobs_api, "get_job_summary", missing_job)

    response = client.get(
        "/jobs/test-job",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}