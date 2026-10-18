import hashlib
import json

from app.config import PROJECT_ROOT, get_settings
from app.database import SessionLocal
from app.models import Post
from app.schemas.post import PostInput
from app.services.embedding_text import EMBEDDING_TASK_TYPE


def load_frozen_cases():
    baseline = json.loads(
        (
            PROJECT_ROOT / "docs" / "heldout-baseline.json"
        ).read_text(encoding="utf-8-sig")
    )

    if baseline["label_file"] != "data/heldout.json":
        raise ValueError("Unexpected baseline label file")

    raw = (
        PROJECT_ROOT / "data" / "heldout.json"
    ).read_bytes()

    actual_hash = hashlib.sha256(raw).hexdigest()

    if actual_hash != baseline["label_sha256"].lower():
        raise ValueError(
            "Evaluation labels differ from the frozen baseline"
        )

    settings = get_settings()

    if (
        settings.embedding_model != baseline["embedding_model"]
        or settings.embedding_dimensions != baseline["dimensions"]
        or settings.min_match_similarity
        != baseline["min_match_similarity"]
        or EMBEDDING_TASK_TYPE != baseline["task_type"]
    ):
        raise ValueError(
            "Current settings differ from the frozen baseline"
        )

    cases = json.loads(raw.decode("utf-8-sig"))

    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must be a nonempty list")

    posts = []
    seen = set()
    positive_count = 0

    for case in cases:
        if case.get("reviewed") is not True:
            raise ValueError("Every case must be reviewed")

        post = PostInput.model_validate({
            "id": case["id"],
            "title": case["title"],
            "content": case["content"],
            "required_subject": case["required_subject"],
        })

        if not post.id.startswith("eval_") or post.id in seen:
            raise ValueError(
                f"Invalid or duplicate evaluation ID: {post.id}"
            )

        seen.add(post.id)

        image_ids = case["acceptable_image_ids"]
        expected = case["expected_status"]

        if (
            not isinstance(image_ids, list)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in image_ids
            )
            or len(image_ids) != len(set(image_ids))
        ):
            raise ValueError("Invalid acceptable image IDs")

        if expected not in {"match", "no_confident_match"}:
            raise ValueError("Invalid expected status")

        if (expected == "match") != bool(image_ids):
            raise ValueError(
                f"Status and labels disagree: {post.id}"
            )

        positive_count += expected == "match"
        posts.append(post)

    if (
        len(posts) != baseline["cases"]
        or positive_count != baseline["matchable_cases"]
        or len(posts) - positive_count
        != baseline["no_match_cases"]
    ):
        raise ValueError("Case counts differ from the baseline")

    return cases, baseline, posts


def main():
    _, _, posts = load_frozen_cases()
    inserted = 0

    with SessionLocal.begin() as session:
        for post in posts:
            existing = session.get(
                Post,
                ("demo", post.id),
            )

            if existing is None:
                session.add(Post(
                    tenant_id="demo",
                    **post.model_dump(),
                ))
                inserted += 1
            elif (
                existing.title != post.title
                or existing.content != post.content
                or existing.required_subject
                != post.required_subject
            ):
                raise ValueError(
                    f"Existing evaluation post differs: {post.id}"
                )

    print(f"Validated frozen evaluation posts: {len(posts)}")
    print(f"Inserted: {inserted}")
    print(f"Unchanged: {len(posts) - inserted}")


if __name__ == "__main__":
    main()