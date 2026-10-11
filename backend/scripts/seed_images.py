import hashlib
import json

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter
from sqlalchemy.dialects.postgresql import insert

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image


TENANT_ID = "demo"


class ManifestEntry(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    filename: str = Field(min_length=1)
    source_url: HttpUrl
    creator: str = Field(min_length=1)
    license_url: HttpUrl


def main():
    manifest_path = PROJECT_ROOT / "data" / "manifest.json"
    images_folder = (PROJECT_ROOT / "data" / "images").resolve()

    raw_data = json.loads(
        manifest_path.read_text(encoding="utf-8-sig")
    )
    entries = TypeAdapter(list[ManifestEntry]).validate_python(
        raw_data
    )

    records = []
    seen_ids = set()
    seen_checksums = {}

    # Validate every file before starting the database transaction.
    for entry in entries:
        if entry.id in seen_ids:
            raise ValueError(f"Duplicate image ID: {entry.id}")
        seen_ids.add(entry.id)

        image_path = (images_folder / entry.filename).resolve()

        if not image_path.is_relative_to(images_folder):
            raise ValueError(f"File is outside images folder: {entry.id}")

        if not image_path.is_file():
            raise FileNotFoundError(f"Missing file: {entry.filename}")

        checksum = hashlib.sha256(
            image_path.read_bytes()
        ).hexdigest()

        if checksum in seen_checksums:
            other_id = seen_checksums[checksum]
            raise ValueError(
                f"Identical image files: {other_id} and {entry.id}"
            )
        seen_checksums[checksum] = entry.id

        records.append({
            "tenant_id": TENANT_ID,
            "id": entry.id,
            "file_path": image_path.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "checksum": checksum,
            "source_url": str(entry.source_url),
            "creator": entry.creator,
            "license_url": str(entry.license_url),
            "status": "pending",
        })

    inserted = 0
    skipped = 0

    with SessionLocal.begin() as session:
        for record in records:
            statement = (
                insert(Image)
                .values(**record)
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "id"]
                )
                .returning(Image.id)
            )

            new_id = session.execute(
                statement
            ).scalar_one_or_none()

            if new_id is not None:
                inserted += 1
            else:
                existing = session.get(
                    Image,
                    (TENANT_ID, record["id"]),
                )

                if (
                    existing.checksum != record["checksum"]
                    or existing.file_path != record["file_path"]
                ):
                    raise ValueError(
                        f"Existing image changed: {record['id']}. "
                        "Review it before replacing its database record."
                    )

                skipped += 1

    print(f"Manifest entries: {len(entries)}")
    print(f"Inserted: {inserted}")
    print(f"Already registered: {skipped}")


if __name__ == "__main__":
    main()