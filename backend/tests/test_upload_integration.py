import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import images as images_api
from app.database import engine
from app.main import create_app
from app.models import Image
from app.repositories import uploads, workspaces
from app.services import image_files, upload_storage
from app.services.auth import AuthenticatedUser, require_user


pytestmark = pytest.mark.integration


@pytest.fixture(params=["", "/api"])
def upload_flow(request, monkeypatch, tmp_path):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    monkeypatch.setattr(uploads, "SessionLocal", factory)
    monkeypatch.setattr(workspaces, "SessionLocal", factory)
    monkeypatch.setattr(images_api, "SessionLocal", factory)
    monkeypatch.setattr(upload_storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(image_files, "PROJECT_ROOT", tmp_path)

    issuer = "https://upload-test.clerk.accounts.dev"
    suffix = uuid4().hex
    first = AuthenticatedUser(
        issuer=issuer,
        user_id=f"user_first_{suffix}",
        session_id="sess_first",
    )
    second = AuthenticatedUser(
        issuer=issuer,
        user_id=f"user_second_{suffix}",
        session_id="sess_second",
    )
    identity = {"user": first}

    application = create_app(frontend_dir=tmp_path / "frontend")
    application.dependency_overrides[require_user] = (
        lambda: identity["user"]
    )

    try:
        tenant = workspaces.get_or_create_workspace(
            issuer, first.user_id
        )
        with TestClient(application) as client:
            yield SimpleNamespace(
                app=application,
                client=client,
                prefix=request.param,
                factory=factory,
                root=tmp_path,
                tenant=tenant,
                identity=identity,
                second=second,
            )
    finally:
        transaction.rollback()
        connection.close()


def jpeg_bytes():
    output = BytesIO()
    exif = PillowImage.Exif()
    exif[315] = "Private embedded metadata"

    with PillowImage.new(
        "RGB", (12, 8), color="orange"
    ) as image:
        image.save(output, format="JPEG", exif=exif)

    return output.getvalue()


def upload_image(ctx, data=None):
    return ctx.client.post(
        f"{ctx.prefix}/images",
        data={"creator": "Example photographer"},
        files={
            "file": (
                "photo.jpg",
                jpeg_bytes() if data is None else data,
                "image/jpeg",
            )
        },
    )


def test_upload_can_be_retrieved_by_owner(upload_flow):
    ctx = upload_flow
    response = upload_image(ctx)

    assert response.status_code == 201
    image_id = response.json()["image_id"]
    assert response.json()["status"] == "pending"

    downloaded = ctx.client.get(
        f"{ctx.prefix}/images/{image_id}/file"
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/jpeg"
    assert downloaded.headers["cache-control"] == "private, no-store"

    with PillowImage.open(BytesIO(downloaded.content)) as image:
        image.load()
        assert image.size == (12, 8)
        assert len(image.getexif()) == 0

    with ctx.factory() as session:
        record = session.get(Image, (ctx.tenant, image_id))
        assert record is not None
        assert record.checksum == hashlib.sha256(
            downloaded.content
        ).hexdigest()
        assert (ctx.root / record.file_path).is_file()

    attribution = ctx.client.get(
        f"{ctx.prefix}/images/{image_id}/attribution"
    )
    assert attribution.status_code == 200
    assert attribution.json()["creator"] == "Example photographer"


def test_duplicate_upload_keeps_one_record_and_file(upload_flow):
    ctx = upload_flow
    data = jpeg_bytes()

    first = upload_image(ctx, data)
    second = upload_image(ctx, data)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["image_id"] == second.json()["image_id"]

    with ctx.factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.tenant_id == ctx.tenant)
        )
        assert count == 1

    assert len(list(
        (ctx.root / "data" / "uploads").rglob("*.jpg")
    )) == 1


def test_other_account_cannot_retrieve_image(upload_flow):
    ctx = upload_flow
    response = upload_image(ctx)
    assert response.status_code == 201
    image_id = response.json()["image_id"]

    ctx.identity["user"] = ctx.second

    for suffix in ("file", "attribution"):
        response = ctx.client.get(
            f"{ctx.prefix}/images/{image_id}/{suffix}",
            headers={"X-Tenant-ID": ctx.tenant},
        )
        assert response.status_code == 404


def test_signed_out_requests_cannot_upload_or_retrieve(upload_flow):
    ctx = upload_flow
    response = upload_image(ctx)
    assert response.status_code == 201
    image_id = response.json()["image_id"]

    ctx.app.dependency_overrides.clear()

    assert upload_image(ctx).status_code == 401

    for suffix in ("file", "attribution"):
        response = ctx.client.get(
            f"{ctx.prefix}/images/{image_id}/{suffix}",
            headers={"X-Tenant-ID": ctx.tenant},
        )
        assert response.status_code == 401


def test_invalid_image_creates_no_file_or_record(upload_flow):
    ctx = upload_flow

    response = upload_image(ctx, b"not a JPEG")
    assert response.status_code == 422
    assert not (ctx.root / "data" / "uploads").exists()

    with ctx.factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.tenant_id == ctx.tenant)
        )
        assert count == 0