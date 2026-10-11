from app.config import PROJECT_ROOT, get_settings
from app.repositories.images import save_classification
from app.services.classification import (
    ClassificationResult,
    assess_classification,
)


def main():
    saved_path = PROJECT_ROOT / "data" / "processed" / "img_001.json"

    saved_result = ClassificationResult.model_validate_json(
        saved_path.read_text(encoding="utf-8-sig")
    )

    # Apply the current confidence threshold to validated metadata.
    result = assess_classification(
        saved_result.metadata,
        min_confidence=get_settings().min_classification_confidence,
    )

    save_classification(
        tenant_id="demo",
        image_id="img_001",
        result=result,
        # The model used for this previously captured result.
        vision_model="gemini-3.8-flash",
    )

    print(f"Saved img_001 to PostgreSQL: {result.status}")


if __name__ == "__main__":
    main()