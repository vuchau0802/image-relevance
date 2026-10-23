import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import upload_storage as storage
from app.services.upload_validation import InvalidImageUploadError


@pytest.fixture
def upload_project(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    return tmp_path


def jpeg_bytes():
    output = BytesIO()
    with Image.new("RGB", (12, 8), color="orange") as image:
        image.save(output, format="JPEG")
    return output.getvalue()


def test_upload_is_stored_inside_its_workspace(upload_project):
    tenant = "ws_" + "a" * 32

    result = storage.store_image_upload(tenant, jpeg_bytes())
    path = upload_project / result.file_path

    assert path.is_file()
    assert path.parent == upload_project / "data" / "uploads" / tenant
    assert path.name == f"{result.image_id}.jpg"
    assert not Path(result.file_path).is_absolute()
    assert result.width == 12
    assert result.height == 8
    assert result.checksum == hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    with Image.open(path) as image:
        image.load()
        assert image.format == "JPEG"


def test_repeated_uploads_get_distinct_filenames(upload_project):
    tenant = "ws_" + "a" * 32
    data = jpeg_bytes()

    first = storage.store_image_upload(tenant, data)
    second = storage.store_image_upload(tenant, data)

    assert first.image_id != second.image_id
    assert first.file_path != second.file_path
    assert first.checksum == second.checksum
    assert (upload_project / first.file_path).is_file()
    assert (upload_project / second.file_path).is_file()


def test_workspaces_use_separate_folders(upload_project):
    first_tenant = "ws_" + "a" * 32
    second_tenant = "ws_" + "b" * 32

    first = storage.store_image_upload(first_tenant, jpeg_bytes())
    second = storage.store_image_upload(second_tenant, jpeg_bytes())

    first_path = upload_project / first.file_path
    second_path = upload_project / second.file_path

    assert first_path.parent.name == first_tenant
    assert second_path.parent.name == second_tenant
    assert first_path.parent != second_path.parent


@pytest.mark.parametrize(
    "tenant",
    ["../outside", "ws_../../outside", "demo", "", None],
)
def test_invalid_workspace_creates_no_files(upload_project, tenant):
    with pytest.raises(ValueError, match="workspace identifier"):
        storage.store_image_upload(tenant, jpeg_bytes())

    assert not (upload_project / "data").exists()


def test_invalid_image_creates_no_files(upload_project):
    with pytest.raises(InvalidImageUploadError):
        storage.store_image_upload(
            "ws_" + "a" * 32,
            b"not an image",
        )

    assert not (upload_project / "data").exists()


def test_filename_collision_preserves_existing_file(
    upload_project, monkeypatch
):
    monkeypatch.setattr(
        storage,
        "uuid4",
        lambda: SimpleNamespace(hex="c" * 32),
    )
    tenant = "ws_" + "a" * 32

    first = storage.store_image_upload(tenant, jpeg_bytes())
    path = upload_project / first.file_path
    original = path.read_bytes()

    with pytest.raises(FileExistsError):
        storage.store_image_upload(tenant, jpeg_bytes())

    assert path.read_bytes() == original