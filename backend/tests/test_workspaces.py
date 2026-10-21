from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models import Workspace
from app.repositories import workspaces


pytestmark = pytest.mark.integration


@pytest.fixture
def workspace_database(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(workspaces, "SessionLocal", factory)

    try:
        yield factory, uuid4().hex
    finally:
        transaction.rollback()
        connection.close()


def test_repeated_requests_return_same_workspace(workspace_database):
    factory, suffix = workspace_database
    issuer = "https://workspace-test.clerk.accounts.dev"
    user = f"user_{suffix}"

    first = workspaces.get_or_create_workspace(issuer, user)
    second = workspaces.get_or_create_workspace(issuer, user)

    assert first == second
    assert first.startswith("ws_")
    assert len(first) <= 50

    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Workspace)
            .where(
                Workspace.auth_issuer == issuer,
                Workspace.auth_user_id == user,
            )
        )

    assert count == 1


def test_different_users_receive_different_workspaces(workspace_database):
    _, suffix = workspace_database
    issuer = "https://workspace-test.clerk.accounts.dev"

    first = workspaces.get_or_create_workspace(
        issuer, f"user_a_{suffix}"
    )
    second = workspaces.get_or_create_workspace(
        issuer, f"user_b_{suffix}"
    )

    assert first != second


def test_same_user_id_under_different_issuers_is_separate(
    workspace_database,
):
    _, suffix = workspace_database
    user = f"user_{suffix}"

    first = workspaces.get_or_create_workspace(
        "https://first-test.clerk.accounts.dev", user
    )
    second = workspaces.get_or_create_workspace(
        "https://second-test.clerk.accounts.dev", user
    )

    assert first != second


def test_workspace_persists_the_account_identity(workspace_database):
    factory, suffix = workspace_database
    issuer = "https://workspace-test.clerk.accounts.dev"
    user = f"user_{suffix}"

    workspace_id = workspaces.get_or_create_workspace(issuer, user)

    with factory() as session:
        record = session.get(Workspace, workspace_id)

        assert record is not None
        assert record.auth_issuer == issuer
        assert record.auth_user_id == user


def test_concurrent_requests_create_one_workspace(monkeypatch):
    # Separate connections are required for a real concurrency check.
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(workspaces, "SessionLocal", factory)

    issuer = "https://concurrency-test.clerk.accounts.dev"
    user = f"user_{uuid4().hex}"
    barrier = Barrier(4)

    def create():
        barrier.wait(timeout=10)
        return workspaces.get_or_create_workspace(issuer, user)

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(create) for _ in range(4)]
            workspace_ids = [
                future.result(timeout=30) for future in futures
            ]

        assert len(set(workspace_ids)) == 1

        with factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(Workspace)
                .where(
                    Workspace.auth_issuer == issuer,
                    Workspace.auth_user_id == user,
                )
            )

        assert count == 1
    finally:
        # Remove only this test's uniquely identified account.
        with factory.begin() as session:
            session.execute(
                delete(Workspace).where(
                    Workspace.auth_issuer == issuer,
                    Workspace.auth_user_id == user,
                )
            )