import pytest
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.api.dependencies import require_workspace
from app.main import create_app


@pytest.fixture
def jobs_client(tmp_path):
    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = lambda: "ws_test"
    with TestClient(application) as client:
        yield client


def test_job_status_uses_verified_workspace(monkeypatch, jobs_client):
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

    response = jobs_client.get(
        "/jobs/test-job",
        headers={"X-Tenant-ID": "tenant-a"},
    )

    assert response.status_code == 200
    assert response.json()["pending"] == 2
    assert calls == [("ws_test", "test-job")]


def test_missing_authentication_is_rejected(monkeypatch, jobs_client):
    del jobs_client.app.dependency_overrides[require_workspace]
    def unexpected_lookup(**kwargs):
        raise AssertionError("Database lookup should not occur")

    monkeypatch.setattr(
        jobs_api,
        "get_job_summary",
        unexpected_lookup,
    )

    response = jobs_client.get("/jobs/test-job")

    assert response.status_code == 401


def test_job_not_found_returns_404(monkeypatch, jobs_client):
    def missing_job(tenant_id, job_id):
        assert tenant_id == "ws_test"
        raise ValueError("Job not found for this tenant")

    monkeypatch.setattr(jobs_api, "get_job_summary", missing_job)

    response = jobs_client.get(
        "/jobs/test-job",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}
