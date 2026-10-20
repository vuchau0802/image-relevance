from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class PostInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=10000)
    required_subject: str = Field(min_length=1, max_length=200)

class PostSummary(BaseModel):
    id: str
    title: str
    required_subject: str


class PostListResponse(BaseModel):
    items: list[PostSummary]
    next_offset: int | None

def validate_post_corpus(data: object) -> list[PostInput]:
    posts = TypeAdapter(list[PostInput]).validate_python(data)

    if not posts:
        raise ValueError("Post corpus must not be empty")

    ids = [post.id for post in posts]

    if len(ids) != len(set(ids)):
        raise ValueError("Post corpus contains duplicate IDs")

    return posts