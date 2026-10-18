import json

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image, Post
from app.schemas.post import PostInput
from app.services.embedding_text import prepare_post_input
from app.services.image_files import verify_registered_image


POST_REQUIREMENTS = {
    "eval_005": [
        {"feature": "curved_body", "expected": "present"},
    ],
    "eval_006": [
        {"feature": "parked", "expected": "present"},
        {"feature": "rider", "expected": "absent"},
    ],
    "eval_009": [
        {"feature": "snow", "expected": "present"},
    ],
}

IMAGE_IDS = [
    "img_001",
    "img_002",
    "img_003",
    "img_004",
    "img_005",
    "img_022",
    "img_024",
]

FEATURES = [
    "snow",
    "parked",
    "rider",
    "curved_body",
]


def main():
    destination = (
        PROJECT_ROOT / "data" / "context-v2-pilot.json"
    )

    if destination.exists():
        raise FileExistsError(
            "Pilot annotation file already exists"
        )

    posts = []
    images = []

    with SessionLocal() as session:
        for post_id, requirements in POST_REQUIREMENTS.items():
            record = session.get(Post, ("demo", post_id))

            if record is None:
                raise ValueError(f"Missing post: {post_id}")

            post = PostInput(
                id=record.id,
                title=record.title,
                content=record.content,
                required_subject=record.required_subject,
            )
            prepared = prepare_post_input(post)

            posts.append({
                "post_id": post_id,
                "input_hash": prepared.input_hash,
                "requirements": {
                    "requirements": requirements,
                },
                "reviewed": False,
            })

        for image_id in IMAGE_IDS:
            record = session.get(Image, ("demo", image_id))

            if record is None:
                raise ValueError(f"Missing image: {image_id}")

            verify_registered_image(
                record.file_path,
                record.checksum,
            )

            images.append({
                "image_id": image_id,
                "image_checksum": record.checksum,
                "facts": [
                    {
                        "feature": feature,
                        "state": "unknown",
                        "source": "manual_review",
                        "explanation": "Awaiting visual review.",
                    }
                    for feature in FEATURES
                ],
                "reviewed": False,
            })

    payload = {
        "version": "manual-v2-pilot",
        "purpose": (
            "Development pilot using previously inspected failures; "
            "not held-out evaluation."
        ),
        "posts": posts,
        "images": images,
    }

    with destination.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")

    print(f"Post requirement drafts: {len(posts)}")
    print(f"Image evidence drafts: {len(images)}")
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()