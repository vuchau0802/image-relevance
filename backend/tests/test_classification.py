import pytest

from app.schemas.image import ImageMetadata
from app.services.classification import assess_classification


@pytest.mark.parametrize(
    "confidence, expected_status",
    [
        (0.94, "completed"),
        (0.40, "needs_review"),
        (0.70, "completed"),
    ],
)
def test_confidence_decision(confidence, expected_status):
    metadata = ImageMetadata(
        subject="red fox",
        category="animal",
        attributes=["orange fur"],
        caption="A red fox standing outdoors",
        confidence=confidence,
    )

    result = assess_classification(
        metadata,
        min_confidence=0.70,
    )

    assert result.status == expected_status
    assert result.metadata == metadata
    assert result.reason


def test_invalid_threshold_is_rejected():
    metadata = ImageMetadata(
        subject="red fox",
        category="animal",
        attributes=[],
        caption="A red fox",
        confidence=0.94,
    )

    with pytest.raises(ValueError):
        assess_classification(metadata, min_confidence=1.5)