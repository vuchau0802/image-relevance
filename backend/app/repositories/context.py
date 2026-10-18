import re

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Image,
    ImageContextRecord,
    Post,
    PostContextRecord,
)
from app.schemas.context import (
    ContextRequirements,
    SceneEvidence,
)
from app.schemas.post import PostInput
from app.services.embedding_text import prepare_post_input


def _validate_identity(tenant_id, source_id, version):
    for name, value, maximum in (
        ("tenant_id", tenant_id, 50),
        ("source_id", source_id, 50),
        ("version", version, 50),
    ):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > maximum
        ):
            raise ValueError(f"Invalid {name}")


def _prepare_post(record):
    return prepare_post_input(PostInput(
        id=record.id,
        title=record.title,
        content=record.content,
        required_subject=record.required_subject,
    ))


def save_post_context(
    tenant_id: str,
    post_id: str,
    input_hash: str,
    version: str,
    requirements: ContextRequirements,
    *,
    reviewed: bool = False,
) -> bool:
    _validate_identity(tenant_id, post_id, version)

    if (
        not isinstance(input_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", input_hash)
    ):
        raise ValueError("Invalid input_hash")

    if not isinstance(reviewed, bool):
        raise ValueError("reviewed must be a boolean")

    validated = ContextRequirements.model_validate(requirements)
    payload = validated.model_dump(mode="json")
    review_status = "reviewed" if reviewed else "needs_review"

    with SessionLocal.begin() as session:
        # Serialize context writes for this source.
        post = session.execute(
            select(Post)
            .where(
                Post.tenant_id == tenant_id,
                Post.id == post_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if post is None:
            raise ValueError("Post not found for this tenant")

        if _prepare_post(post).input_hash != input_hash:
            raise ValueError(
                "Post text changed; context input hash is stale"
            )

        identity = (
            tenant_id,
            post_id,
            input_hash,
            version,
        )
        existing = session.get(
            PostContextRecord,
            identity,
        )

        if existing is not None:
            if (
                existing.requirements != payload
                or existing.review_status != review_status
            ):
                raise ValueError(
                    "Context version already exists with different "
                    "content or review status; use a new version"
                )

            return False

        session.add(PostContextRecord(
            tenant_id=tenant_id,
            post_id=post_id,
            input_hash=input_hash,
            version=version,
            requirements=payload,
            review_status=review_status,
        ))

    return True


def get_current_post_context(
    tenant_id: str,
    post_id: str,
    version: str,
) -> ContextRequirements | None:
    _validate_identity(tenant_id, post_id, version)

    with SessionLocal() as session:
        post = session.get(
            Post,
            (tenant_id, post_id),
        )

        if post is None:
            return None

        current_hash = _prepare_post(post).input_hash

        record = session.get(
            PostContextRecord,
            (
                tenant_id,
                post_id,
                current_hash,
                version,
            ),
        )

        if record is None or record.review_status != "reviewed":
            return None

        return ContextRequirements.model_validate(
            record.requirements
        )


def _validate_scene_facts(facts):
    if not isinstance(facts, list) or len(facts) > 100:
        raise ValueError(
            "Scene facts must be a list with at most 100 entries"
        )

    validated = [
        SceneEvidence.model_validate(
            fact.model_dump()
            if isinstance(fact, SceneEvidence)
            else fact
        )
        for fact in facts
    ]

    features = [fact.feature for fact in validated]

    if len(features) != len(set(features)):
        raise ValueError("Duplicate scene evidence features")

    return sorted(
        validated,
        key=lambda fact: fact.feature,
    )


def save_image_context(
    tenant_id: str,
    image_id: str,
    image_checksum: str,
    version: str,
    facts: list[SceneEvidence],
    *,
    reviewed: bool = False,
) -> bool:
    _validate_identity(tenant_id, image_id, version)

    if (
        not isinstance(image_checksum, str)
        or not re.fullmatch(
            r"[0-9a-f]{64}", image_checksum
        )
    ):
        raise ValueError("Invalid image_checksum")

    if not isinstance(reviewed, bool):
        raise ValueError("reviewed must be a boolean")

    validated = _validate_scene_facts(facts)
    payload = [
        fact.model_dump(mode="json")
        for fact in validated
    ]
    review_status = "reviewed" if reviewed else "needs_review"

    with SessionLocal.begin() as session:
        image = session.execute(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.id == image_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if image is None:
            raise ValueError(
                "Image not found for this tenant"
            )

        if image.checksum != image_checksum:
            raise ValueError(
                "Image checksum differs from registered source"
            )

        existing = session.get(
            ImageContextRecord,
            (
                tenant_id,
                image_id,
                image_checksum,
                version,
            ),
        )

        if existing is not None:
            if (
                existing.facts != payload
                or existing.review_status != review_status
            ):
                raise ValueError(
                    "Context version already exists with different "
                    "content or review status; use a new version"
                )

            return False

        session.add(ImageContextRecord(
            tenant_id=tenant_id,
            image_id=image_id,
            image_checksum=image_checksum,
            version=version,
            facts=payload,
            review_status=review_status,
        ))

    return True


def get_current_image_context(
    tenant_id: str,
    image_id: str,
    version: str,
) -> list[SceneEvidence] | None:
    _validate_identity(tenant_id, image_id, version)

    with SessionLocal() as session:
        record = session.execute(
            select(ImageContextRecord)
            .join(
                Image,
                (
                    ImageContextRecord.tenant_id
                    == Image.tenant_id
                )
                & (
                    ImageContextRecord.image_id
                    == Image.id
                )
                & (
                    ImageContextRecord.image_checksum
                    == Image.checksum
                ),
            )
            .where(
                ImageContextRecord.tenant_id == tenant_id,
                ImageContextRecord.image_id == image_id,
                ImageContextRecord.version == version,
                ImageContextRecord.review_status == "reviewed",
            )
        ).scalar_one_or_none()

        if record is None:
            return None

        return _validate_scene_facts(record.facts)
