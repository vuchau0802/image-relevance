import hashlib
import json

from pydantic import TypeAdapter
from sqlalchemy import select

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image
from scripts.seed_images import ManifestEntry


CORRECTIONS = {
    "img_037": (
        "https://unsplash.com/photos/three-plates-of-asian-food-on-wood-table--YHSwy6uqvk",
        "Lily Banse",
    ),
    "img_038": (
        "https://unsplash.com/photos/bowl-of-vegetable-salads-IGfIGP5ONV0",
        "Anna Pelzer",
    ),
}


def main():
    entries = TypeAdapter(list[ManifestEntry]).validate_python(
        json.loads(
            (PROJECT_ROOT / "data" / "manifest.json").read_text(
                encoding="utf-8-sig"
            )
        )
    )
    by_id = {entry.id: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("Manifest contains duplicate image IDs")

    for image_id, (source_url, creator) in CORRECTIONS.items():
        entry = by_id[image_id]
        if (
            entry.filename != f"{image_id}.jpg"
            or str(entry.source_url) != source_url
            or entry.creator != creator
            or str(entry.license_url) != "https://unsplash.com/license"
        ):
            raise ValueError(f"Reviewed manifest correction missing: {image_id}")

    images_folder = (PROJECT_ROOT / "data" / "images").resolve()
    with SessionLocal.begin() as session:
        images = session.scalars(
            select(Image)
            .where(
                Image.tenant_id == "demo",
                Image.id.in_(CORRECTIONS),
            )
            .order_by(Image.id)
            .with_for_update()
        ).all()
        if len(images) != 2:
            raise ValueError("Both reviewed images must exist in the demo tenant")

        for image in images:
            entry = by_id[image.id]
            path = (PROJECT_ROOT / image.file_path).resolve()
            expected_path = (images_folder / entry.filename).resolve()
            if not path.is_relative_to(images_folder) or path != expected_path:
                raise ValueError(f"Registered image path differs: {image.id}")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != image.checksum:
                raise ValueError(f"Registered image checksum differs: {image.id}")

            image.source_url = str(entry.source_url)
            image.creator = entry.creator
            image.license_url = str(entry.license_url)

    print("Reviewed provenance synchronized: img_037, img_038")
    print("Image files, classification metadata, and job history were not changed.")


if __name__ == "__main__":
    main()
