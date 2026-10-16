"""Transaction-scoped metadata persistence shared by both processing paths."""

from sqlalchemy.dialects.postgresql import insert

from app.models import ImageMetadataRecord


def persist_classification(session, image, result, vision_model):
    statement = insert(ImageMetadataRecord).values(
        tenant_id=image.tenant_id,
        image_id=image.id,
        **result.metadata.model_dump(),
        vision_model=vision_model,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["tenant_id", "image_id"],
        set_={
            field: getattr(statement.excluded, field)
            for field in (
                "subject", "category", "attributes", "caption",
                "confidence", "vision_model",
            )
        },
    )
    session.execute(statement)
    image.status = result.status
