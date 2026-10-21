import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def frontend_client(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()

    (tmp_path / "index.html").write_text(
        '<!doctype html><html><body>'
        '<div id="root">Test frontend</div>'
        '<script src="/assets/app.js"></script>'
        '</body></html>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text(
        'console.log("test bundle");',
        encoding="utf-8",
    )

    with TestClient(create_app(frontend_dir=tmp_path)) as client:
        yield client


def test_frontend_index_is_served(frontend_client):
    response = frontend_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Test frontend" in response.text


def test_frontend_asset_is_served(frontend_client):
    response = frontend_client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == 'console.log("test bundle");'


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_routes_take_precedence(frontend_client, path):
    response = frontend_client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_api_does_not_return_frontend_html(frontend_client):
    response = frontend_client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert "Test frontend" not in response.text


@pytest.mark.parametrize(
    "path",
    ["/posts", "/api/posts"],
)
def test_post_routes_require_authentication(frontend_client, path):
    response = frontend_client.get(path)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(
        "application/json"
    )


def test_missing_asset_returns_404(frontend_client):
    response = frontend_client.get("/assets/missing.js")

    assert response.status_code == 404


def test_missing_build_returns_clear_error(tmp_path):
    with TestClient(create_app(frontend_dir=tmp_path)) as client:
        response = client.get("/")

        assert response.status_code == 503
        assert "Frontend build unavailable" in response.json()["detail"]

        # API remains usable without a frontend build.
        assert client.get("/api/health").status_code == 200
