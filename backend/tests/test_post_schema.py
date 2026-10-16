import pytest
from pydantic import ValidationError

from app.schemas.post import PostInput, validate_post_corpus


def valid_post():
    return {
        "id": "post_001",
        "title": "Red foxes",
        "content": "Red foxes adapt to urban environments.",
        "required_subject": "red fox",
    }


def test_valid_post_is_trimmed():
    data = valid_post()
    data["title"] = "  Red foxes  "

    post = PostInput.model_validate(data)

    assert post.title == "Red foxes"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"title": "   "},
        {"content": ""},
        {"required_subject": "   "},
        {"id": "x" * 51},
        {"title": "x" * 301},
        {"content": "x" * 10001},
        {"required_subject": "x" * 201},
        {"unexpected_field": True},
    ],
)
def test_invalid_post_is_rejected(changes):
    with pytest.raises(ValidationError):
        PostInput.model_validate(valid_post() | changes)


def test_duplicate_post_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate IDs"):
        validate_post_corpus([valid_post(), valid_post()])


def test_empty_corpus_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        validate_post_corpus([])


def test_distinct_posts_are_accepted():
    first = valid_post()
    second = valid_post() | {"id": "post_002"}

    posts = validate_post_corpus([first, second])

    assert [post.id for post in posts] == [
        "post_001",
        "post_002",
    ]