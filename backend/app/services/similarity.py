import math

from app.services.embedding_vectors import normalize_embedding


def cosine_similarity(
    left: list[float],
    right: list[float],
) -> float:
    if len(left) != len(right):
        raise ValueError(
            "Vectors must have the same dimensions"
        )

    left_normalized = normalize_embedding(left, len(left))
    right_normalized = normalize_embedding(right, len(right))

    score = math.fsum(
        a * b
        for a, b in zip(left_normalized, right_normalized)
    )

    # Limit minor floating-point rounding outside [-1, 1].
    return max(-1.0, min(1.0, score))