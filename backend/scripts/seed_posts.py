import json

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert

from app.config import PROJECT_ROOT
from app.database import SessionLocal
from app.models import Post
from app.schemas.post import validate_post_corpus


TENANT_ID = "demo"


def main():
    path = PROJECT_ROOT / "data" / "posts.json"

    raw_data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    # Validate the complete corpus before opening a transaction.
    posts = validate_post_corpus(raw_data)

    changed = 0

    with SessionLocal.begin() as session:
        for post in posts:
            statement = insert(Post).values(
                tenant_id=TENANT_ID,
                **post.model_dump(),
            )

            statement = statement.on_conflict_do_update(
                index_elements=["tenant_id", "id"],
                set_={
                    "title": statement.excluded.title,
                    "content": statement.excluded.content,
                    "required_subject":
                        statement.excluded.required_subject,
                    "updated_at": func.now(),
                },
                where=or_(
                    Post.title != statement.excluded.title,
                    Post.content != statement.excluded.content,
                    Post.required_subject
                    != statement.excluded.required_subject,
                ),
            ).returning(Post.id)

            changed_id = session.execute(
                statement
            ).scalar_one_or_none()

            if changed_id is not None:
                changed += 1

    print(f"Validated posts: {len(posts)}")
    print(f"Inserted or updated: {changed}")
    print(f"Unchanged: {len(posts) - changed}")


if __name__ == "__main__":
    main()