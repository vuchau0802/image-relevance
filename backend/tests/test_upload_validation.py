import hashlib
from io import BytesIO

import pytest
from PIL import Image

from app.services import upload_validation as validation


def make_image(
    size=(12, 8),
    image_format="JPEG",
    exif=None,
):
    output = BytesIO()

    with Image.new("RGB", size, color="orange") as image:
        options = {}
        if exif is not None:
            options["exif"] = exif

        image.save(output, format=image_format, **options)

    return output.getvalue()


def test_valid_jpeg_is_decoded_and_normalized():
    result = validation.validate_image_upload(make_image())

    assert result.width == 12
    assert result.height == 8

    with Image.open(BytesIO(result.data)) as image:
        image.load()
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (12, 8)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"This is not an image",
        b"\xff\xd8broken-jpeg",
    ],
)
def test_empty_or_invalid_files_are_rejected(data):
    with pytest.raises(validation.InvalidImageUploadError):
        validation.validate_image_upload(data)


def test_png_is_rejected_even_if_named_as_jpeg():
    # Validation uses file contents, not a filename.
    data = make_image(image_format="PNG")

    with pytest.raises(validation.InvalidImageUploadError):
        validation.validate_image_upload(data)


def test_upload_byte_limit_is_enforced(monkeypatch):
    data = make_image()
    monkeypatch.setattr(
        validation, "MAX_UPLOAD_BYTES", len(data) - 1
    )

    with pytest.raises(
        validation.InvalidImageUploadError,
        match="upload limit",
    ):
        validation.validate_image_upload(data)


def test_pixel_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(validation, "MAX_UPLOAD_PIXELS", 10)

    with pytest.raises(
        validation.InvalidImageUploadError,
        match="pixel limit",
    ):
        validation.validate_image_upload(make_image(size=(4, 3)))


def test_original_exif_metadata_is_removed():
    exif = Image.Exif()
    exif[270] = "Private image description"
    exif[315] = "Private photographer name"

    result = validation.validate_image_upload(
        make_image(exif=exif)
    )

    with Image.open(BytesIO(result.data)) as image:
        assert len(image.getexif()) == 0
        assert "exif" not in image.info


def test_exif_orientation_is_applied():
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.

    result = validation.validate_image_upload(
        make_image(size=(12, 8), exif=exif)
    )

    assert (result.width, result.height) == (8, 12)

    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (8, 12)
        assert len(image.getexif()) == 0


def test_checksum_matches_normalized_bytes_and_is_repeatable():
    original = make_image()

    first = validation.validate_image_upload(original)
    second = validation.validate_image_upload(original)

    assert first.checksum == hashlib.sha256(first.data).hexdigest()
    assert second.data == first.data
    assert second.checksum == first.checksum