from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import embedding_jobs, posts
from app.api.dependencies import require_workspace
from app.main import create_app
from app.repositories.embedding_jobs import EmbeddingPostNotFoundError


def job_summary():
    return {
        "job_id": "test-job",
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
def api_context(request, monkeypatch, tmp_path):
    create_job = Mock(return_value="test-job")
    read_summary = Mock(side_effect=lambda **kwargs: job_summary())

    monkeypatch.setattr(
        posts, "create_post_embedding_job", create_job
    )
    monkeypatch.setattr(
        posts, "get_embedding_job_summary", read_summary
    )
    monkeypatch.setattr(
        embedding_jobs, "get_embedding_job_summary", read_summary
    )

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = (
        lambda: "ws_owner"
    )

    with TestClient(application) as client:
        yield SimpleNamespace(
            app=application,
            client=client,
            prefix=request.param,
            create_job=create_job,
            read_summary=read_summary,
        )


def test_prepare_post_returns_job(api_context):
    ctx = api_context

    response = ctx.client.post(
        f"{ctx.prefix}/posts/private-post/embedding-job"
    )

    assert response.status_code == 202
    assert response.json() == job_summary()
    ctx.create_job.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="private-post",
    )
    ctx.read_summary.assert_called_once_with(
        tenant_id="ws_owner",
        job_id="test-job",
    )


def test_missing_or_unowned_post_returns_404(api_context):
    ctx = api_context
    ctx.create_job.side_effect = EmbeddingPostNotFoundError()

    response = ctx.client.post(
        f"{ctx.prefix}/posts/other-post/embedding-job"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}
    ctx.read_summary.assert_not_called()


def test_read_job_returns_summary(api_context):
    ctx = api_context

    response = ctx.client.get(
        f"{ctx.prefix}/embedding-jobs/test-job"
    )

    assert response.status_code == 200
    assert response.json() == job_summary()
    ctx.read_summary.assert_called_once_with(
        tenant_id="ws_owner",
        job_id="test-job",
    )


def test_missing_or_unowned_job_returns_404(api_context):
    ctx = api_context
    ctx.read_summary.side_effect = ValueError("Not found")

    response = ctx.client.get(
        f"{ctx.prefix}/embedding-jobs/other-job"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Embedding job not found"
    }


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/posts/private-post/embedding-job"),
        ("GET", "/embedding-jobs/test-job"),
    ],
)
def test_sign_in_is_required(api_context, method, path):
    ctx = api_context
    ctx.app.dependency_overrides.clear()

    response = ctx.client.request(
        method,
        f"{ctx.prefix}{path}",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 401
    ctx.create_job.assert_not_called()
    ctx.read_summary.assert_not_called()


def test_caller_cannot_override_workspace(api_context):
    ctx = api_context
    headers = {"X-Tenant-ID": "ws_other"}

    prepared = ctx.client.post(
        f"{ctx.prefix}/posts/private-post/embedding-job",
        headers=headers,
        params={"tenant_id": "ws_other"},
    )
    status = ctx.client.get(
        f"{ctx.prefix}/embedding-jobs/test-job",
        headers=headers,
        params={"tenant_id": "ws_other"},
    )

    assert prepared.status_code == 202
    assert status.status_code == 200

    ctx.create_job.assert_called_once_with(
        tenant_id="ws_owner",
        post_id="private-post",
    )
    assert ctx.read_summary.call_count == 2
    for call in ctx.read_summary.call_args_list:
        assert call.kwargs["tenant_id"] == "ws_owner"