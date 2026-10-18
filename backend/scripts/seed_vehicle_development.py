"""Seed reviewed development queries; keep answer labels out of posts."""

import json
import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Image, Post
from app.schemas.post import PostInput


def load_cases():
    path = PROJECT_ROOT / "data" / "vehicle-development.json"
    cases = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or len(cases) != 8:
        raise ValueError("Expected eight vehicle development cases")

    posts = []
    seen = set()
    references = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("reviewed") is not True:
            raise ValueError("Every case must be reviewed")
        post = PostInput.model_validate({
            name: case[name]
            for name in ("id", "title", "content", "required_subject")
        })
        if not re.fullmatch(r"veh_00[1-8]", post.id) or post.id in seen:
            raise ValueError(f"Invalid or duplicate case ID: {post.id}")
        seen.add(post.id)
        reason = case.get("label_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Missing label reason: {post.id}")
        ids = case.get("acceptable_image_ids")
        if not isinstance(ids, list) or any(
            not isinstance(value, str) or not value.strip() for value in ids
        ):
            raise ValueError(f"Invalid image labels: {post.id}")
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate image labels: {post.id}")
        status = case.get("expected_status")
        if status not in {"match", "no_confident_match"}:
            raise ValueError(f"Invalid expected status: {post.id}")
        if (status == "match") != bool(ids):
            raise ValueError(f"Status and image labels disagree: {post.id}")
        references.update(ids)
        posts.append(post)
    return cases, posts, references


def main():
    cases, posts, references = load_cases()
    inserted = 0
    with SessionLocal.begin() as session:
        known = set(session.scalars(
            select(Image.id).where(Image.tenant_id == "demo")
        ))
        if references - known:
            raise ValueError(f"Unknown image IDs: {sorted(references - known)}")
        for post in posts:
            # An existing development query must not silently change.
            statement = insert(Post).values(
                tenant_id="demo", **post.model_dump()
            ).on_conflict_do_nothing(
                index_elements=["tenant_id", "id"]
            ).returning(Post.id)
            created = session.execute(statement).scalar_one_or_none()
            if created is not None:
                inserted += 1
            else:
                record = session.get(Post, ("demo", post.id))
                if record is None or any(
                    getattr(record, name) != getattr(post, name)
                    for name in ("title", "content", "required_subject")
                ):
                    raise ValueError(
                        f"Stored query differs: {post.id}; use a new case ID/version"
                    )
    print(f"Validated vehicle development posts: {len(cases)}")
    print(f"Inserted: {inserted}")
    print(f"Unchanged: {len(posts) - inserted}")


if __name__ == "__main__":
    main()
