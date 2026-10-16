import math

from app.services.retries import InvalidModelResponseError


class InvalidEmbeddingError(InvalidModelResponseError):
    pass


def normalize_embedding(
    values: list[float] | tuple[float, ...],
    expected_dimensions: int,
) -> list[float]:
    if (
        isinstance(expected_dimensions, bool)
        or not isinstance(expected_dimensions, int)
        or not 1 <= expected_dimensions <= 3072
    ):
        raise InvalidEmbeddingError("Invalid embedding dimensions")

    if not isinstance(values, (list, tuple)):
        raise InvalidEmbeddingError("Embedding must be a list or tuple")

    if len(values) != expected_dimensions:
        raise InvalidEmbeddingError(
            "Embedding length differs from configured dimensions"
        )

    vector = []

    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidEmbeddingError(
                "Embedding values must be numbers"
            )

        try:
            number = float(value)
        except (OverflowError, ValueError) as error:
            raise InvalidEmbeddingError(
                "Embedding values must be finite"
            ) from error

        if not math.isfinite(number):
            raise InvalidEmbeddingError(
                "Embedding values must be finite"
            )

        vector.append(number)

    largest = max(abs(value) for value in vector)

    if largest == 0:
        raise InvalidEmbeddingError(
            "Embedding must have nonzero magnitude"
        )

    # Scale first to avoid overflow or underflow when finding the norm.
    scaled = [value / largest for value in vector]
    magnitude = math.hypot(*scaled)

    return [value / magnitude for value in scaled]