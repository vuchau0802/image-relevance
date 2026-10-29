from sqlalchemy import select
from uuid import uuid4
from app.database import SessionLocal
from app.models import Post
from app.schemas.post import (
    PostCreate,
    PostInput,
    PostListResponse,
    PostSummary,
)

def list_posts(
    tenant_id: str,
    offset: int = 0,
    limit: int = 50,
) -> PostListResponse:
    with SessionLocal() as session:
        records = session.scalars(
            select(Post)
            .where(Post.tenant_id == tenant_id)
            .order_by(Post.id)
            .offset(offset)
            .limit(limit + 1)
        ).all()

        items = [
            PostSummary(
                id=record.id,
                title=record.title,
                required_subject=record.required_subject,
            )
            for record in records[:limit]
        ]

    return PostListResponse(
        items=items,
        next_offset=offset + limit if len(records) > limit else None,
    )

def create_post(
    tenant_id: str,
    payload: PostCreate,
) -> PostInput:
    created = PostInput(
        id=f"post_{uuid4().hex}",
        **payload.model_dump(),
    )

    with SessionLocal.begin() as session:
        session.add(Post(
            tenant_id=tenant_id,
            **created.model_dump(),
        ))

    return created

class PostNotFoundError(LookupError):
    pass


def get_post(
    tenant_id: str,
    post_id: str,
) -> PostInput:
    with SessionLocal() as session:
        record = session.get(Post, (tenant_id, post_id))

        if record is None:
            raise PostNotFoundError("Post not found")

        return PostInput(
            id=record.id,
            title=record.title,
            content=record.content,
            required_subject=record.required_subject,
        )


def update_post(
    tenant_id: str,
    post_id: str,
    payload: PostUpdate,
) -> PostInput:
    with SessionLocal.begin() as session:
        record = session.get(
            Post,
            (tenant_id, post_id),
            with_for_update=True,
        )

        if record is None:
            raise PostNotFoundError("Post not found")

        record.title = payload.title
        record.content = payload.content
        record.required_subject = payload.required_subject

        result = PostInput(
            id=record.id,
            title=record.title,
            content=record.content,
            required_subject=record.required_subject,
        )

    return result