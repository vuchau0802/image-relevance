from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import recommendations
from app.api.dependencies import require_workspace
from app.main import create_app
from app.services.ranking import (
    MissingPostEmbeddingError,
    PostNotFoundError,
)


@pytest.fixture
def api_context(monkeypatch, tmp_path):
    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_workspace] = lambda: "ws_test"
    payload = {
        "post_id": "post_test",
        "status": "matched",
        "reason": "Subject-compatible images were ranked.",
        "required_subject": "red fox",
        "model": "test-model",
        "dimensions": 768,
        "candidates_scored": 1,
        "subject_compatible_candidates": 1,
        "subject_rejected_count": 0,
        "missing_current_embeddings": [],
        "results": [
            {
                "image_id": "img_test",
                "subject": "red fox",
                "caption": "A red fox outdoors.",
                "similarity": 0.85,
            }
        ],
    }

    rank = Mock(return_value=payload)
    monkeypatch.setattr(
        recommendations, "rank_post_images", rank
    )

    with TestClient(application) as client:
        yield client, rank, payload


def test_returns_ranked_images(api_context):
    client, rank, payload = api_context

    response = client.get(
        "/posts/post_test/images?top=3",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 200
    assert response.json() == payload
    rank.assert_called_once_with(
        tenant_id="ws_test",
        post_id="post_test",
        top=3,
    )


def test_missing_authentication_is_rejected(api_context):
    client, rank, _ = api_context
    del client.app.dependency_overrides[require_workspace]

    response = client.get("/posts/post_test/images")

    assert response.status_code == 401
    rank.assert_not_called()


@pytest.mark.parametrize("top", ["0", "51", "abc"])
def test_invalid_top_is_rejected(api_context, top):
    client, rank, _ = api_context

    response = client.get(
        f"/posts/post_test/images?top={top}",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 422
    rank.assert_not_called()


def test_other_workspace_returns_generic_404(api_context):
    client, rank, _ = api_context
    client.app.dependency_overrides[require_workspace] = lambda: "ws_other"
    rank.side_effect = PostNotFoundError(
        "Post not found for this tenant."
    )

    response = client.get(
        "/posts/post_test/images",
        headers={"X-Tenant-ID": "different-tenant"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}
    rank.assert_called_once_with(
        tenant_id="ws_other",
        post_id="post_test",
        top=5,
    )


def test_missing_embedding_returns_409(api_context):
    client, rank, _ = api_context
    rank.side_effect = MissingPostEmbeddingError(
        "Current post embedding is missing."
    )

    response = client.get(
        "/posts/post_test/images",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Current post embedding is unavailable"
    }


def test_no_match_returns_empty_results(api_context):
    client, _, payload = api_context
    payload.update({
        "status": "no_confident_match",
        "reason": "No image passed the required-subject guard.",
        "subject_compatible_candidates": 0,
        "subject_rejected_count": 1,
        "results": [],
    })

    response = client.get(
        "/posts/post_test/images",
        headers={"X-Tenant-ID": "demo"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "no_confident_match"
    assert response.json()["results"] == []
