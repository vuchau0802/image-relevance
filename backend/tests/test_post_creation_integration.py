from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.main import create_app
from app.models import Post
from app.repositories import posts, workspaces
from app.schemas.post import PostCreate
from app.services.auth import AuthenticatedUser, require_user


pytestmark = pytest.mark.integration


@pytest.fixture
def creation_database(monkeypatch, tmp_path):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(posts, "SessionLocal", factory)
    monkeypatch.setattr(workspaces, "SessionLocal", factory)

    suffix = uuid4().hex
    issuer = "https://post-test.clerk.accounts.dev"

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

    application = create_app(frontend_dir=tmp_path)
    application.dependency_overrides[require_user] = lambda: first

    try:
        first_workspace = workspaces.get_or_create_workspace(
            issuer, first.user_id
        )
        second_workspace = workspaces.get_or_create_workspace(
            issuer, second.user_id
        )

        with TestClient(application) as client:
            yield SimpleNamespace(
                factory=factory,
                app=application,
                client=client,
                first=first,
                second=second,
                first_workspace=first_workspace,
                second_workspace=second_workspace,
                payload=PostCreate(
                    title="  My private post  ",
                    content="  A post about red foxes.  ",
                    required_subject="  red fox  ",
                ),
            )
    finally:
        transaction.rollback()
        connection.close()


def test_post_is_persisted_under_its_workspace(creation_database):
    ctx = creation_database

    created = posts.create_post(ctx.first_workspace, ctx.payload)

    with ctx.factory() as session:
        record = session.get(
            Post, (ctx.first_workspace, created.id)
        )

        assert record is not None
        assert record.title == "My private post"
        assert record.content == "A post about red foxes."
        assert record.required_subject == "red fox"

        assert session.get(
            Post, (ctx.second_workspace, created.id)
        ) is None


def test_new_posts_get_distinct_server_ids(creation_database):
    ctx = creation_database

    first = posts.create_post(ctx.first_workspace, ctx.payload)
    second = posts.create_post(ctx.first_workspace, ctx.payload)

    assert first.id != second.id
    assert first.id.startswith("post_")
    assert second.id.startswith("post_")
    assert len(first.id) <= 50
    assert len(second.id) <= 50

    stored = posts.list_posts(ctx.first_workspace)
    assert {item.id for item in stored.items} == {
        first.id, second.id
    }


def test_workspace_lists_only_its_own_posts(creation_database):
    ctx = creation_database

    first = posts.create_post(ctx.first_workspace, ctx.payload)
    second = posts.create_post(
        ctx.second_workspace,
        PostCreate(
            title="Other account's post",
            content="A post about motor scooters.",
            required_subject="motor scooter",
        ),
    )

    own_list = posts.list_posts(ctx.first_workspace)
    other_list = posts.list_posts(ctx.second_workspace)

    assert [item.id for item in own_list.items] == [first.id]
    assert [item.id for item in other_list.items] == [second.id]


@pytest.mark.parametrize("prefix", ["", "/api"])
def test_create_and_list_follow_verified_account(
    creation_database, prefix
):
    ctx = creation_database

    response = ctx.client.post(
        f"{prefix}/posts",
        json=ctx.payload.model_dump(),
        headers={"X-Tenant-ID": ctx.second_workspace},
    )

    assert response.status_code == 201
    post_id = response.json()["id"]

    with ctx.factory() as session:
        assert session.get(
            Post, (ctx.first_workspace, post_id)
        ) is not None
        assert session.get(
            Post, (ctx.second_workspace, post_id)
        ) is None

    own_response = ctx.client.get(f"{prefix}/posts")
    assert own_response.status_code == 200
    assert [item["id"] for item in own_response.json()["items"]] == [
        post_id
    ]

    ctx.app.dependency_overrides[require_user] = lambda: ctx.second

    other_response = ctx.client.get(
        f"{prefix}/posts",
        headers={"X-Tenant-ID": ctx.first_workspace},
    )

    assert other_response.status_code == 200
    assert other_response.json()["items"] == []