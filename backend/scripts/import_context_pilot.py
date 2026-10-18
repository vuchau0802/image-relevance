import argparse
import json

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image, Post
from app.repositories.context import (
    save_image_context,
    save_post_context,
)
from app.schemas.context import (
    ContextRequirements,
    SceneEvidence,
)
from app.schemas.post import PostInput
from app.services.embedding_text import prepare_post_input
from app.services.image_files import verify_registered_image


def validate_pilot():
    path = PROJECT_ROOT / "data" / "context-v2-pilot.json"
    data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    version = data["version"]

    if (
        not isinstance(version, str)
        or not version.strip()
        or len(version) > 50
    ):
        raise ValueError("Invalid context version")

    if not data["posts"] or not data["images"]:
        raise ValueError("Pilot must contain posts and images")

    posts = []
    images = []
    seen_posts = set()
    seen_images = set()

    with SessionLocal() as session:
        for entry in data["posts"]:
            post_id = entry["post_id"]

            if post_id in seen_posts:
                raise ValueError(f"Duplicate post: {post_id}")
            seen_posts.add(post_id)

            if entry.get("reviewed") is not True:
                raise ValueError(f"Unreviewed post: {post_id}")

            requirements = ContextRequirements.model_validate(
                entry["requirements"]
            )

            record = session.get(Post, ("demo", post_id))
            if record is None:
                raise ValueError(f"Post not found: {post_id}")

            prepared = prepare_post_input(PostInput(
                id=record.id,
                title=record.title,
                content=record.content,
                required_subject=record.required_subject,
            ))

            if prepared.input_hash != entry["input_hash"]:
                raise ValueError(f"Stale post hash: {post_id}")

            posts.append({
                "post_id": post_id,
                "input_hash": prepared.input_hash,
                "requirements": requirements,
            })

        for entry in data["images"]:
            image_id = entry["image_id"]

            if image_id in seen_images:
                raise ValueError(f"Duplicate image: {image_id}")
            seen_images.add(image_id)

            if entry.get("reviewed") is not True:
                raise ValueError(f"Unreviewed image: {image_id}")

            raw_facts = entry["facts"]
            if (
                not isinstance(raw_facts, list)
                or len(raw_facts) > 100
            ):
                raise ValueError(f"Invalid facts: {image_id}")

            facts = [
                SceneEvidence.model_validate(fact)
                for fact in raw_facts
            ]

            features = [fact.feature for fact in facts]
            if len(features) != len(set(features)):
                raise ValueError(
                    f"Duplicate evidence features: {image_id}"
                )

            for fact in facts:
                if "awaiting visual review" in (
                    fact.explanation.casefold()
                ):
                    raise ValueError(
                        f"Placeholder explanation: {image_id}"
                    )

            record = session.get(Image, ("demo", image_id))
            if record is None:
                raise ValueError(f"Image not found: {image_id}")

            if record.checksum != entry["image_checksum"]:
                raise ValueError(
                    f"Stale image checksum: {image_id}"
                )

            verify_registered_image(
                record.file_path,
                record.checksum,
            )

            images.append({
                "image_id": image_id,
                "image_checksum": record.checksum,
                "facts": facts,
            })

    return version, posts, images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate-only",
        action="store_true",
    )
    args = parser.parse_args()

    version, posts, images = validate_pilot()

    print(f"Version: {version}")
    print(f"Validated posts: {len(posts)}")
    print(f"Validated images: {len(images)}")

    if args.validate_only:
        print("Validation only; no database records changed.")
        return

    inserted_posts = 0
    inserted_images = 0

    for entry in posts:
        inserted_posts += save_post_context(
            tenant_id="demo",
            version=version,
            reviewed=True,
            **entry,
        )

    for entry in images:
        inserted_images += save_image_context(
            tenant_id="demo",
            version=version,
            reviewed=True,
            **entry,
        )

    print(f"New post-context records: {inserted_posts}")
    print(f"New image-context records: {inserted_images}")
    print("Context import completed.")


if __name__ == "__main__":
    main()