import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Post
from app.schemas.post import PostInput


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main():
    path = PROJECT_ROOT / "data" / "calibration.json"
    cases = json.loads(path.read_text(encoding="utf-8-sig"))

    if not isinstance(cases, list) or not cases:
        raise ValueError("Calibration must be a nonempty list")

    posts = []
    referenced_images = set()
    seen_ids = set()

    for case in cases:
        if case.get("reviewed") is not True:
            raise ValueError("All calibration cases must be reviewed")

        post = PostInput.model_validate({
            "id": case["id"],
            "title": case["title"],
            "content": case["content"],
            "required_subject": case["required_subject"],
        })

        if not post.id.startswith("cal_"):
            raise ValueError("Calibration IDs must start with cal_")

        if post.id in seen_ids:
            raise ValueError(f"Duplicate calibration ID: {post.id}")

        seen_ids.add(post.id)

        image_ids = case.get("acceptable_image_ids")
        if (
            not isinstance(image_ids, list)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in image_ids
            )
        ):
            raise ValueError("Invalid acceptable_image_ids")

        expected = case.get("expected_status")
        if expected not in {"match", "no_confident_match"}:
            raise ValueError("Invalid expected_status")

        if (expected == "match") != bool(image_ids):
            raise ValueError(
                "Match cases need image IDs; no-match cases need none"
            )

        referenced_images.update(image_ids)
        posts.append(post)

    changed = 0

    with SessionLocal.begin() as session:
        existing_images = set(session.scalars(
            select(Image.id).where(
                Image.tenant_id == "demo"
            )
        ))

        missing = referenced_images - existing_images
        if missing:
            raise ValueError(
                f"Unknown calibration image IDs: {sorted(missing)}"
            )

        for post in posts:
            record = session.get(Post, ("demo", post.id))

            if record is None:
                session.add(Post(
                    tenant_id="demo",
                    **post.model_dump(),
                ))
                changed += 1
                continue

            fields = {
                "title": post.title,
                "content": post.content,
                "required_subject": post.required_subject,
            }

            if any(
                getattr(record, name) != value
                for name, value in fields.items()
            ):
                for name, value in fields.items():
                    setattr(record, name, value)
                changed += 1

    print(f"Validated calibration posts: {len(posts)}")
    print(f"Inserted or updated: {changed}")
    print(f"Unchanged: {len(posts) - changed}")


if __name__ == "__main__":
    main()