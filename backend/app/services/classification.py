from typing import Literal

from pydantic import BaseModel

from app.schemas.image import ImageMetadata


class ClassificationResult(BaseModel):
    status: Literal["completed", "needs_review"]
    metadata: ImageMetadata
    reason: str


def assess_classification(
    metadata: ImageMetadata,
    min_confidence: float,
) -> ClassificationResult:
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")

    if metadata.confidence < min_confidence:
        return ClassificationResult(
            status="needs_review",
            metadata=metadata,
            reason=(
                f"Confidence {metadata.confidence:.2f} is below "
                f"the required threshold {min_confidence:.2f}."
            ),
        )

    return ClassificationResult(
        status="completed",
        metadata=metadata,
        reason="Classification meets the confidence threshold.",
    )