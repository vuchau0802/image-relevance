from app.schemas.image import ImageMetadata
from app.schemas.post import PostInput
from app.services.embedding_text import (
    prepare_image_input,
    prepare_post_input,
)


def image_metadata():
    return ImageMetadata(
        subject="red fox",
        category="animal",
        attributes=["orange fur", "bushy tail"],
        caption="A red fox standing on a road.",
        confidence=0.95,
    )


def post_input(**changes):
    data = {
        "id": "post_001",
        "title": "Urban foxes",
        "content": "Red foxes adapt to urban environments.",
        "required_subject": "red fox",
    }
    return PostInput.model_validate(data | changes)


def test_attribute_order_and_duplicates_do_not_change_input():
    first = image_metadata()
    second = first.model_copy(update={
        "attributes": [
            "bushy tail",
            "orange fur",
            "orange fur",
        ],
    })

    assert prepare_image_input(first) == prepare_image_input(second)


def test_caption_change_invalidates_image_hash():
    first = image_metadata()
    second = first.model_copy(update={
        "caption": "A red fox sleeping in grass.",
    })

    assert (
        prepare_image_input(first).input_hash
        != prepare_image_input(second).input_hash
    )


def test_content_change_invalidates_post_hash():
    first = post_input()
    second = post_input(content="Red foxes care for their young.")

    assert (
        prepare_post_input(first).input_hash
        != prepare_post_input(second).input_hash
    )


def test_required_subject_change_invalidates_post_hash():
    first = post_input()
    second = post_input(required_subject="gray wolf")

    assert (
        prepare_post_input(first).input_hash
        != prepare_post_input(second).input_hash
    )


def test_post_id_is_not_part_of_embedding_text():
    first = post_input(id="post_001")
    second = post_input(id="post_002")

    assert prepare_post_input(first) == prepare_post_input(second)
    assert "post_001" not in prepare_post_input(first).text


def test_equivalent_unicode_and_whitespace_are_normalized():
    first = post_input(title="Cafe\u0301   foxes")
    second = post_input(title="Café foxes")

    assert prepare_post_input(first) == prepare_post_input(second)