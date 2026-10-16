import math

import pytest

from app.services.embedding_vectors import (
    InvalidEmbeddingError,
    normalize_embedding,
)
from app.services.retries import is_retryable


def test_vector_is_normalized():
    result = normalize_embedding([3.0, 4.0], 2)

    assert result == pytest.approx([0.6, 0.8])
    assert math.hypot(*result) == pytest.approx(1.0)


@pytest.mark.parametrize("scale", [1e308, 5e-324])
def test_extreme_finite_values_are_normalized_safely(scale):
    result = normalize_embedding([scale, scale], 2)

    assert all(math.isfinite(value) for value in result)
    assert math.hypot(*result) == pytest.approx(1.0)


def test_input_is_not_modified():
    original = [3.0, 4.0]

    normalize_embedding(original, 2)

    assert original == [3.0, 4.0]


@pytest.mark.parametrize(
    "values",
    [
        [],
        [1.0],
        [0.0, 0.0],
        [float("nan"), 1.0],
        [float("inf"), 1.0],
        [True, 1.0],
        ["1", 1.0],
        [[1.0], 1.0],
    ],
)
def test_invalid_vectors_are_rejected(values):
    with pytest.raises(InvalidEmbeddingError):
        normalize_embedding(values, 2)


@pytest.mark.parametrize("dimensions", [0, 3073, True, "2"])
def test_invalid_dimension_settings_are_rejected(dimensions):
    with pytest.raises(InvalidEmbeddingError):
        normalize_embedding([1.0, 2.0], dimensions)


def test_invalid_provider_vector_is_retryable():
    error = InvalidEmbeddingError("Invalid provider vector")

    assert is_retryable(error)