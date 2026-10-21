import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.parametrize("prefix", ["", "/api"])
@pytest.mark.parametrize(
    "path",
    [
        "/posts",
        "/posts/post_001/images",
        "/images/img_001/file",
        "/images/img_001/attribution",
        "/jobs/test-job",
    ],
)
def test_tenant_header_alone_cannot_access_content(
    tmp_path, prefix, path
):
    application = create_app(frontend_dir=tmp_path)

    with TestClient(application) as client:
        response = client.get(
            f"{prefix}{path}",
            headers={"X-Tenant-ID": "demo"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "A valid sign-in session is required"
    }
