from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import images
from app.api.dependencies import require_workspace
from app.main import create_app
from app.repositories.embedding_jobs import (
    EmbeddingImageNotFoundError,
    EmbeddingImageNotReadyError,
)


def summary():
    return {
        "job_id": "image-embedding-job",
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


@pytest.fixture(params=["", "/api"])
def embedding_api(request, monkeypatch, tmp_path):
    create_job = Mock(return_value="image-embedding-job")
    read_summary = Mock(return_value=summary())

    monkeypatch.setattr(
        images, "create_image_embedding_job", create_job
    )
    monkeypatch.setattr(
        images, "get_embedding_job_summary", read_summary
    )

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            path=f"{request.param}/images/private-image/embedding-job",
            create_job=create_job,
            read_summary=read_summary,
        )


def test_image_embedding_returns_job(embedding_api):
    ctx = embedding_api

    response = ctx.client.post(ctx.path)

    assert response.status_code == 202
    assert response.json() == summary()
    ctx.create_job.assert_called_once_with(
        tenant_id="ws_owner",
        image_id="private-image",
    )
    ctx.read_summary.assert_called_once_with(
        tenant_id="ws_owner",
        job_id="image-embedding-job",
    )


def test_missing_or_unowned_image_returns_404(embedding_api):
    ctx = embedding_api
    ctx.create_job.side_effect = EmbeddingImageNotFoundError()

    response = ctx.client.post(ctx.path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}
    ctx.read_summary.assert_not_called()


def test_unfinished_analysis_returns_409(embedding_api):
    ctx = embedding_api
    ctx.create_job.side_effect = EmbeddingImageNotReadyError(
        "Image analysis must complete before embedding preparation"
    )

    response = ctx.client.post(ctx.path)

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Image analysis must complete before embedding preparation"
        )
    }
    ctx.read_summary.assert_not_called()


def test_image_embedding_requires_sign_in(embedding_api):
    ctx = embedding_api
    ctx.app.dependency_overrides.clear()

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 401
    ctx.create_job.assert_not_called()
    ctx.read_summary.assert_not_called()


def test_caller_cannot_override_workspace(embedding_api):
    ctx = embedding_api

    response = ctx.client.post(
        ctx.path,
        headers={"X-Tenant-ID": "ws_other"},
        params={"tenant_id": "ws_other"},
        json={"tenant_id": "ws_other"},
    )

    assert response.status_code == 202
    ctx.create_job.assert_called_once_with(
        tenant_id="ws_owner",
        image_id="private-image",
    )
    ctx.read_summary.assert_called_once_with(
        tenant_id="ws_owner",
        job_id="image-embedding-job",
    )