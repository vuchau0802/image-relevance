import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.schemas.upload import MAX_UPLOAD_BYTES, MAX_UPLOAD_PIXELS


class InvalidImageUploadError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedImageUpload:
    data: bytes
    checksum: str
    width: int
    height: int


def validate_image_upload(data: bytes) -> ValidatedImageUpload:
    if not data:
        raise InvalidImageUploadError("The image file is empty.")

    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImageUploadError(
            "The image exceeds the 10 MiB upload limit."
        )

    try:
        with Image.open(BytesIO(data), formats=["JPEG"]) as image:
            width, height = image.size

            if width * height > MAX_UPLOAD_PIXELS:
                raise InvalidImageUploadError(
                    "The image exceeds the 20 million pixel limit."
                )

            image.verify()

        # Reopen after verify() and fully decode the pixels.
        with Image.open(BytesIO(data), formats=["JPEG"]) as image:
            image.load()

            with ImageOps.exif_transpose(image) as oriented:
                with oriented.convert("RGB") as rgb:
                    # A fresh image carries no original EXIF/GPS metadata.
                    with Image.new("RGB", rgb.size) as clean:
                        clean.paste(rgb)

                        output = BytesIO()
                        clean.save(
                            output,
                            format="JPEG",
                            quality=90,
                        )
                        normalized = output.getvalue()
                        width, height = clean.size

    except InvalidImageUploadError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
        SyntaxError,
    ) as error:
        raise InvalidImageUploadError(
            "Upload a valid, readable JPEG image."
        ) from error

    if len(normalized) > MAX_UPLOAD_BYTES:
        raise InvalidImageUploadError(
            "The normalized image exceeds the 10 MiB limit."
        )

    return ValidatedImageUpload(
        data=normalized,
        checksum=hashlib.sha256(normalized).hexdigest(),
        width=width,
        height=height,
    )