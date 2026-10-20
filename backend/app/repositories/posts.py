from sqlalchemy import select

from app.database import SessionLocal
from app.models import Post
from app.schemas.post import PostListResponse, PostSummary


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