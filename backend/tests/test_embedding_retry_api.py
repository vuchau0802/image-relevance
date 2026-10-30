from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import embedding_jobs
from app.api.dependencies import require_workspace
from app.main import create_app
from app.repositories.embedding_jobs import (
    EmbeddingRetryNotAllowedError,
    EmbeddingRetrySourceNotFoundError,
)


FAILED_JOB_ID = "a19a0d90-52a3-41b7-8096-50124c994213"


def summary():
    return {
        "job_id": "retry-job",
        "status": "queued",
        "model": "test-model",
        "dimensions": 768,
        "task_type": "SEMANTIC_SIMILARITY",
        "total": 1,
        "pending": 1,
        "processing": 0,
        "completed": 0,
        "failed": 0,
    }


@pytest.fixture(params=[
    ("", "post"),
    ("", "image"),
    ("/api", "post"),
    ("/api", "image"),
])
def retry_api(request, monkeypatch, tmp_path):
    prefix, source_type = request.param
    retry_job = Mock(return_value="retry-job")
    read_summary = Mock(return_value=summary())

    monkeypatch.setattr(
        embedding_jobs, "retry_embedding_job", retry_job
    )
    monkeypatch.setattr(
        embedding_jobs,
        "get_embedding_job_summary",
        read_summary,
    )

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            source_type=source_type,
            path=(
                f"{prefix}/embedding-jobs/{FAILED_JOB_ID}"
                f"/retry/{source_type}/source_test"
            ),
            retry_job=retry_job,
            read_summary=read_summary,
        )


def test_retry_returns_job_summary(retry_api):
    ctx = retry_api

    response = ctx.client.post(ctx.path)

    assert response.status_code == 202
    assert response.json() == summary()
    ctx.retry_job.assert_called_once_with(
        tenant_id="ws_owner",
        source_type=ctx.source_type,
        source_id="source_test",
        failed_job_id=FAILED_JOB_ID,
    )
    ctx.read_summary.assert_called_once_with(
        tenant_id="ws_owner",
        job_id="retry-job",
    )


def test_missing_or_unowned_source_returns_404(retry_api):
    ctx = retry_api
    ctx.retry_job.side_effect = (
        EmbeddingRetrySourceNotFoundError()
    )

    response = ctx.client.post(ctx.path)

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Embedding source not found"
    }
    ctx.read_summary.assert_not_called()


def test_invalid_retry_returns_409(retry_api):
    ctx = retry_api
    ctx.retry_job.side_effect = EmbeddingRetryNotAllowedError(
        "Content has changed. Start a new preparation job."
    )

    response = ctx.client.post(ctx.path)

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Content has changed. Start a new preparation job."
        )
    }
    ctx.read_summary.assert_not_called()


def test_retry_requires_sign_in(retry_api):
    ctx = retry_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "ws_owner"},
    )

    assert response.status_code == 401
    ctx.retry_job.assert_not_called()
    ctx.read_summary.assert_not_called()


def test_caller_cannot_override_workspace(retry_api):
    ctx = retry_api

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        params={"tenant_id": "ws_other"},
        json={"tenant_id": "ws_other"},
    )

    assert response.status_code == 202
    ctx.retry_job.assert_called_once_with(
        tenant_id="ws_owner",
        source_type=ctx.source_type,
        source_id="source_test",
        failed_job_id=FAILED_JOB_ID,
    )


def test_malformed_job_id_is_rejected(retry_api):
    ctx = retry_api

    response = ctx.client.post(
        ctx.path.replace(FAILED_JOB_ID, "invalid-job-id")
    )

    assert response.status_code == 422
    ctx.retry_job.assert_not_called()
    ctx.read_summary.assert_not_called()