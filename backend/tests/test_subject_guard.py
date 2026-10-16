import pytest

from app.services.subject_guard import subject_matches


@pytest.mark.parametrize(
    "required,observed,expected",
    [
        ("red fox", "red fox", True),
        ("Vulpes vulpes", "red fox", True),
        ("gray wolf", "grey wolf", True),
        ("gray wolf", "Canis lupus", True),
        ("  RED FOX  ", "red fox", True),
        ("red fox", "gray wolf", False),
        ("gray wolf", "red fox", False),
        ("gray wolf", "coyote", False),
        ("gray wolf", "American black bear", False),
        ("unknown animal", "unknown animal", False),
    ],
)
def test_subject_matches(required, observed, expected):
    assert subject_matches(required, observed) is expected

@pytest.mark.parametrize(
    "required,observed,category,caption,expected",
    [
        (
            "dog",
            "Welsh Corgi puppy",
            "animal",
            "",
            True,
        ),
        (
            "dog",
            "gray wolf",
            "animal",
            "",
            False,
        ),
        (
            "black bear",
            "American black bear",
            "animal",
            "",
            True,
        ),
        (
            "black bear",
            "brown bear",
            "animal",
            "",
            False,
        ),
        (
            "motor scooter",
            "Vespa scooter",
            "vehicle",
            "",
            True,
        ),
        (
            "Volkswagen Beetle",
            "vintage car",
            "vehicle",
            "",
            False,
        ),
        (
            "pizza",
            "mixed meal",
            "food",
            "A pizza served alongside steak.",
            True,
        ),
        (
            "vegetable salad",
            "salad bowl",
            "food",
            "A salad with lettuce, tomatoes, and cabbage.",
            True,
        ),
        (
            "vegetable salad",
            "salad bowl",
            "food",
            "An unidentified salad.",
            False,
        ),
        (
            "Yosemite waterfall",
            "Yosemite Valley",
            "landscape",
            "Granite cliffs beside a waterfall.",
            True,
        ),
        (
            "Yosemite waterfall",
            "Yosemite Valley",
            "landscape",
            "Mountains and a forest.",
            False,
        ),
        (
            "Yosemite waterfall",
            "mountain landscape",
            "landscape",
            "A waterfall in an unidentified mountain range.",
            False,
        ),
        (
            "red fox",
            "red fox",
            "vehicle",
            "",
            False,
        ),
        (
            "emperor penguin",
            "gray wolf",
            "animal",
            "",
            False,
        ),
    ],
)
def test_extended_subject_guard(
    required, observed, category, caption, expected
):
    assert subject_matches(
        required,
        observed,
        category=category,
        caption=caption,
    ) is expected