from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmbeddingFields:
    tenant_id: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    task_type: Mapped[str] = mapped_column(String(50))
    input_hash: Mapped[str] = mapped_column(String(64))

    vector: Mapped[list[float]] = mapped_column(
        ARRAY(Float, dimensions=1)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


def embedding_checks(prefix):
    return (
        CheckConstraint(
            "dimensions BETWEEN 1 AND 3072",
            name=f"ck_{prefix}_dimensions",
        ),
        CheckConstraint(
            "cardinality(vector) = dimensions "
            "AND COALESCE(array_ndims(vector), 0) = 1",
            name=f"ck_{prefix}_vector_shape",
        ),
        CheckConstraint(
            "array_position(vector, NULL) IS NULL",
            name=f"ck_{prefix}_vector_no_nulls",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name=f"ck_{prefix}_input_hash",
        ),
    )


class ImageEmbedding(EmbeddingFields, Base):
    __tablename__ = "image_embeddings"

    image_id: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "image_id",
            "model",
            "dimensions",
            "task_type",
            "input_hash",
            name="pk_image_embeddings",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "image_id"],
            ["images.tenant_id", "images.id"],
            ondelete="CASCADE",
            name="fk_image_embeddings_image",
        ),
        *embedding_checks("image_embeddings"),
    )


class PostEmbedding(EmbeddingFields, Base):
    __tablename__ = "post_embeddings"

    post_id: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "post_id",
            "model",
            "dimensions",
            "task_type",
            "input_hash",
            name="pk_post_embeddings",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "post_id"],
            ["posts.tenant_id", "posts.id"],
            ondelete="CASCADE",
            name="fk_post_embeddings_post",
        ),
        *embedding_checks("post_embeddings"),
    )