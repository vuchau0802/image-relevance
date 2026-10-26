import re
import unicodedata


def normalize_subject(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


SUBJECT_GROUPS = {
    "red fox": {
        "red fox",
        "red foxes",
        "vulpes vulpes",
    },
    "gray wolf": {
        "gray wolf",
        "gray wolves",
        "grey wolf",
        "grey wolves",
        "canis lupus",
    },
    "coyote": {
        "coyote",
        "coyotes",
    },
    "dog": {
        "dog",
        "dogs",
        "domestic dog",
        "domestic dogs",
        "welsh corgi puppy",
        "nova scotia duck tolling retriever",
        "yellow labrador retriever puppy",
    },
    "black bear": {
        "black bear",
        "american black bear",
    },
    "brown bear": {
        "brown bear",
        "grizzly bear",
    },
    "volkswagen beetle": {
        "volkswagen beetle",
        "vw beetle",
    },
    "motor scooter": {
        "motor scooter",
        "motor scooters",
        "vespa scooter",
    },
    "pizza": {
        "pizza",
        "bbq chicken pizza",
    },
    "vegetable salad": {
        "vegetable salad",
    },
    "forest": {
        "forest",
        "forests",
        "woodland",
        "woodlands",
    },
    "yosemite waterfall": {
        "yosemite waterfall",
    },
    "emperor penguin": {
        "emperor penguin",
        "emperor penguins",
    },
}

SUBJECT_ALIASES = {
    alias: canonical
    for canonical, aliases in SUBJECT_GROUPS.items()
    for alias in aliases
}

EXPECTED_CATEGORIES = {
    "red fox": "animal",
    "gray wolf": "animal",
    "coyote": "animal",
    "dog": "animal",
    "black bear": "animal",
    "brown bear": "animal",
    "emperor penguin": "animal",
    "volkswagen beetle": "vehicle",
    "motor scooter": "vehicle",
    "pizza": "food",
    "vegetable salad": "food",
    "forest": "landscape",
    "yosemite waterfall": "landscape",
}

VEGETABLE_WORDS = {
    "avocado",
    "cabbage",
    "carrot",
    "carrots",
    "corn",
    "cucumber",
    "cucumbers",
    "lettuce",
    "pepper",
    "peppers",
    "radish",
    "radishes",
    "spinach",
    "tomato",
    "tomatoes",
}


def canonical_subject(value: str) -> str | None:
    return SUBJECT_ALIASES.get(normalize_subject(value))


def subject_matches(
    required_subject: str,
    observed_subject: str,
    *,
    category: str | None = None,
    caption: str = "",
) -> bool:
    required = canonical_subject(required_subject)

    if required is None:
        return False

    if (
        category is not None
        and normalize_subject(category)
        != EXPECTED_CATEGORIES[required]
    ):
        return False

    observed = canonical_subject(observed_subject)

    if observed == required:
        return True

    subject_words = set(re.findall(
        r"[a-z]+", normalize_subject(observed_subject)
    ))
    caption_words = set(re.findall(
        r"[a-z]+", normalize_subject(caption)
    ))
    all_words = subject_words | caption_words

    if required == "pizza":
        return (
            category == "food"
            and "pizza" in all_words
        )

    if required == "vegetable salad":
        return (
            category == "food"
            and "salad" in all_words
            and len(caption_words & VEGETABLE_WORDS) >= 2
        )

    if required == "yosemite waterfall":
        return (
            category == "landscape"
            and "yosemite" in all_words
            and bool(
                {"waterfall", "waterfalls"} & all_words
            )
        )

    return False