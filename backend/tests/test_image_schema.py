import pytest
from pydantic import ValidationError

from app.schemas.image import ImageMetadata


def valid_metadata():
    return {
        "subject": "red fox",
        "category": "animal",
        "attributes": ["orange fur", "forest"],
        "caption": "A red fox standing in a forest",
        "confidence": 0.94,
    }


def test_valid_metadata_is_accepted():
    metadata = ImageMetadata.model_validate(valid_metadata())

    assert metadata.subject == "red fox"
    assert metadata.confidence == 0.94


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"subject": "   "},
        {"category": "unknown"},
        {"unexpected_field": "value"},
    ],
)
def test_invalid_metadata_is_rejected(changes):
    data = valid_metadata()
    data.update(changes)

    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)


def test_missing_caption_is_rejected():
    data = valid_metadata()
    del data["caption"]

    with pytest.raises(ValidationError):
        ImageMetadata.model_validate(data)