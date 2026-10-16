from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.services import ranking


def image_row(image_id, subject="red fox"):
    return (
        image_id,
        SimpleNamespace(
            subject=subject,
            category="animal",
            attributes=["standing outdoors"],
            caption=f"A {subject} standing outdoors.",
            confidence=0.99,
        ),
    )


@pytest.fixture
def ranking_context(monkeypatch):
    post = SimpleNamespace(
        id="post_test",
        title="Red fox behavior",
        content="Observing red foxes outdoors.",
        required_subject="red fox",
    )

    rows = [
        image_row("img_a"),
        image_row("img_b"),
        image_row("img_wolf", "gray wolf"),
    ]

    post_query = Mock()
    post_query.scalar_one_or_none.return_value = post

    image_query = Mock()
    image_query.all.return_value = rows

    session = MagicMock()
    session.execute.side_effect = [
        post_query,
        image_query,
    ]

    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = session

    vectors = {
        ("post", "post_test"): [1.0, 0.0],
        ("image", "img_a"): [0.8, 0.6],
        ("image", "img_b"): [0.6, 0.8],
        ("image", "img_wolf"): [1.0, 0.0],
    }

    def read_cache(key):
        assert key.tenant_id == "test-tenant"
        assert key.model == "test-model"
        assert key.dimensions == 2
        return vectors.get((key.source_type, key.source_id))

    settings = SimpleNamespace(
        embedding_model="test-model",
        embedding_dimensions=2,
        min_match_similarity=0.5,
    )

    monkeypatch.setattr(
        ranking,
        "get_settings",
        lambda: settings,
    )

    monkeypatch.setattr(
        ranking, "SessionLocal", session_factory
    )
    monkeypatch.setattr(
        ranking, "get_cached_embedding", read_cache
    )

    return SimpleNamespace(
        post=post,
        rows=rows,
        vectors=vectors,
        post_query=post_query,
        settings=settings,
    )


def test_ranks_compatible_images_and_rejects_wolf(
    ranking_context,
):
    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert isinstance(result, dict)
    assert result["status"] == "matched"
    assert result["candidates_scored"] == 3
    assert result["subject_rejected_count"] == 1
    assert [
        item["image_id"] for item in result["results"]
    ] == ["img_a", "img_b"]
    assert result["results"][0]["similarity"] == pytest.approx(
        0.8
    )


def test_equal_scores_use_image_id_for_stable_order(
    ranking_context,
):
    ctx = ranking_context
    ctx.rows.reverse()
    ctx.vectors[("image", "img_b")] = [0.8, 0.6]

    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert [
        item["image_id"] for item in result["results"]
    ] == ["img_a", "img_b"]


def test_top_limits_results(ranking_context):
    result = ranking.rank_post_images(
        "test-tenant", "post_test", top=1
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["image_id"] == "img_a"
    assert result["subject_compatible_candidates"] == 2


def test_missing_image_embedding_marks_incomplete(
    ranking_context,
):
    del ranking_context.vectors[("image", "img_a")]

    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert result["status"] == "incomplete"
    assert result["missing_current_embeddings"] == ["img_a"]


def test_no_compatible_subject_returns_no_match(
    ranking_context,
):
    ranking_context.post.required_subject = "emperor penguin"

    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert result["status"] == "no_confident_match"
    assert result["results"] == []


def test_missing_post_embedding_raises(ranking_context):
    del ranking_context.vectors[("post", "post_test")]

    with pytest.raises(
        ValueError, match="Current post embedding is missing"
    ):
        ranking.rank_post_images(
            "test-tenant", "post_test"
        )


def test_missing_post_raises(ranking_context):
    ranking_context.post_query.scalar_one_or_none.return_value = (
        None
    )

    with pytest.raises(ValueError, match="Post not found"):
        ranking.rank_post_images(
            "test-tenant", "post_test"
        )


@pytest.mark.parametrize("top", [0, 51, True])
def test_invalid_top_is_rejected(top):
    with pytest.raises(ValueError, match="top must"):
        ranking.rank_post_images(
            "test-tenant", "post_test", top=top
        )

@pytest.mark.parametrize(
    "threshold,expected_status,expected_ids",
    [
        (0.7999, "matched", ["img_a"]),
        (0.8, "matched", ["img_a"]),
        (0.8001, "no_confident_match", []),
    ],
)
def test_similarity_threshold_boundary(
    ranking_context,
    threshold,
    expected_status,
    expected_ids,
):
    ranking_context.settings.min_match_similarity = threshold

    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert result["status"] == expected_status
    assert [
        item["image_id"] for item in result["results"]
    ] == expected_ids

    # Both foxes pass the subject guard, even when the
    # similarity threshold rejects them.
    assert result["subject_compatible_candidates"] == 2


def test_high_similarity_does_not_override_subject_guard(
    ranking_context,
):
    ctx = ranking_context
    ctx.settings.min_match_similarity = 0.85

    # The wolf scores 1.0; the compatible foxes score below 0.85.
    result = ranking.rank_post_images(
        "test-tenant", "post_test"
    )

    assert result["status"] == "no_confident_match"
    assert result["results"] == []
    assert result["subject_rejected_count"] == 1
    assert "similarity threshold" in result["reason"]