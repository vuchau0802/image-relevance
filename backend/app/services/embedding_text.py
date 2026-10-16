import hashlib
import unicodedata
from dataclasses import dataclass

from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput


EMBEDDING_TASK_TYPE = "SEMANTIC_SIMILARITY"


@dataclass(frozen=True)
class PreparedEmbeddingInput:
    text: str
    input_hash: str


def clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return " ".join(normalized.split())


def prepare_input(text: str) -> PreparedEmbeddingInput:
    return PreparedEmbeddingInput(
        text=text,
        input_hash=hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest(),
    )


def prepare_image_input(
    metadata: ImageMetadata,
) -> PreparedEmbeddingInput:
    attributes = sorted({
        clean_text(attribute)
        for attribute in metadata.attributes
    })

    text = "\n".join([
        f"Subject: {clean_text(metadata.subject)}",
        f"Category: {metadata.category}",
        f"Attributes: {'; '.join(attributes)}",
        f"Caption: {clean_text(metadata.caption)}",
    ])

    return prepare_input(text)


def prepare_post_input(
    post: PostInput,
) -> PreparedEmbeddingInput:
    text = "\n".join([
        f"Title: {clean_text(post.title)}",
        f"Subject: {clean_text(post.required_subject)}",
        f"Content: {clean_text(post.content)}",
    ])

    return prepare_input(text)