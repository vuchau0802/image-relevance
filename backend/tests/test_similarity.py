import pytest

from app.services.embedding_vectors import InvalidEmbeddingError
from app.services.similarity import cosine_similarity


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ([1.0, 0.0], [1.0, 0.0], 1.0),
        ([1.0, 0.0], [0.0, 1.0], 0.0),
        ([1.0, 0.0], [-1.0, 0.0], -1.0),
        ([3.0, 4.0], [6.0, 8.0], 1.0),
        ([1.0, 1.0], [1.0, 0.0], 2 ** -0.5),
    ],
)
def test_known_similarity(left, right, expected):
    assert cosine_similarity(left, right) == pytest.approx(
        expected
    )


def test_similarity_is_symmetric():
    left = [1.0, 2.0, 3.0]
    right = [4.0, 1.0, -2.0]

    assert cosine_similarity(left, right) == pytest.approx(
        cosine_similarity(right, left)
    )


def test_different_dimensions_are_rejected():
    with pytest.raises(ValueError, match="same dimensions"):
        cosine_similarity([1.0, 0.0], [1.0])


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        [0.0, 0.0],
        [float("nan"), 1.0],
        [float("inf"), 1.0],
    ],
)
def test_invalid_vectors_are_rejected(invalid):
    with pytest.raises(InvalidEmbeddingError):
        cosine_similarity(invalid, invalid)