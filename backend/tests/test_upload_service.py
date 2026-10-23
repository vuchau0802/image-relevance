from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.schemas.upload import ImageUploadResponse
from app.services import upload_storage, uploads
from app.services.upload_validation import InvalidImageUploadError


@pytest.fixture
def upload_context(monkeypatch, tmp_path):
    monkeypatch.setattr(upload_storage, "PROJECT_ROOT", tmp_path)

    register = Mock(
        side_effect=lambda **kwargs: ImageUploadResponse(
            image_id=kwargs["upload"].image_id,
            status="pending",
        )
    )
    monkeypatch.setattr(uploads, "register_image_upload", register)

    return SimpleNamespace(
        root=tmp_path,
        tenant="ws_" + "a" * 32,
        register=register,
    )


def jpeg_bytes():
    output = BytesIO()
    with Image.new("RGB", (12, 8), color="orange") as image:
        image.save(output, format="JPEG")
    return output.getvalue()


def stored_files(ctx):
    return list((ctx.root / "data" / "uploads").rglob("*.jpg"))


def test_success_keeps_file_and_registers_attribution(upload_context):
    ctx = upload_context

    result = uploads.create_uploaded_image(
        ctx.tenant,
        jpeg_bytes(),
        creator="Example creator",
        source_url="https://example.com/photo",
        license_url="https://example.com/license",
    )

    files = stored_files(ctx)
    assert len(files) == 1
    assert files[0].name == f"{result.image_id}.jpg"
    assert result.status == "pending"

    ctx.register.assert_called_once()
    arguments = ctx.register.call_args.kwargs
    assert arguments["tenant_id"] == ctx.tenant
    assert arguments["creator"] == "Example creator"
    assert arguments["source_url"] == "https://example.com/photo"
    assert arguments["license_url"] == "https://example.com/license"


def test_duplicate_removes_only_new_file(upload_context):
    ctx = upload_context
    data = jpeg_bytes()

    first = uploads.create_uploaded_image(
        ctx.tenant, data, creator="Original creator"
    )
    original_path = stored_files(ctx)[0]
    original_bytes = original_path.read_bytes()

    ctx.register.side_effect = None
    ctx.register.return_value = first

    duplicate = uploads.create_uploaded_image(
        ctx.tenant, data, creator="Another creator"
    )

    assert duplicate.image_id == first.image_id
    assert stored_files(ctx) == [original_path]
    assert original_path.read_bytes() == original_bytes


@pytest.mark.parametrize("creator", ["", "   ", "x" * 201])
def test_invalid_creator_writes_nothing(upload_context, creator):
    ctx = upload_context

    with pytest.raises(ValueError, match="creator"):
        uploads.create_uploaded_image(
            ctx.tenant, jpeg_bytes(), creator=creator
        )

    ctx.register.assert_not_called()
    assert not (ctx.root / "data").exists()


def test_registration_failure_preserves_file(upload_context):
    ctx = upload_context
    ctx.register.side_effect = RuntimeError(
        "Database commit outcome unknown"
    )

    with pytest.raises(RuntimeError, match="outcome unknown"):
        uploads.create_uploaded_image(
            ctx.tenant, jpeg_bytes(), creator="Example creator"
        )

    assert len(stored_files(ctx)) == 1


def test_cleanup_failure_still_returns_registered_image(
    upload_context, monkeypatch, caplog
):
    ctx = upload_context
    data = jpeg_bytes()

    first = uploads.create_uploaded_image(
        ctx.tenant, data, creator="Original creator"
    )
    original_path = stored_files(ctx)[0]

    ctx.register.side_effect = None
    ctx.register.return_value = first
    monkeypatch.setattr(
        uploads,
        "remove_duplicate_file",
        Mock(side_effect=OSError("File temporarily locked")),
    )

    result = uploads.create_uploaded_image(
        ctx.tenant, data, creator="Another creator"
    )

    assert result.image_id == first.image_id
    assert original_path.is_file()
    assert len(stored_files(ctx)) == 2
    assert "Could not remove duplicate upload" in caplog.text


def test_invalid_image_never_reaches_registration(upload_context):
    ctx = upload_context

    with pytest.raises(InvalidImageUploadError):
        uploads.create_uploaded_image(
            ctx.tenant, b"not an image", creator="Example creator"
        )

    ctx.register.assert_not_called()
    assert not (ctx.root / "data").exists()