from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Workspace


def get_or_create_workspace(
    auth_issuer: str,
    auth_user_id: str,
) -> str:
    if (
        not isinstance(auth_issuer, str)
        or not auth_issuer.strip()
        or auth_issuer != auth_issuer.strip()
        or len(auth_issuer) > 512
    ):
        raise ValueError("Invalid authentication issuer")

    if (
        not isinstance(auth_user_id, str)
        or not auth_user_id.strip()
        or auth_user_id != auth_user_id.strip()
        or len(auth_user_id) > 255
    ):
        raise ValueError("Invalid authentication user ID")

    with SessionLocal.begin() as session:
        statement = (
            insert(Workspace)
            .values(
                id=f"ws_{uuid4().hex}",
                auth_issuer=auth_issuer,
                auth_user_id=auth_user_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_workspaces_account",
            )
            .returning(Workspace.id)
        )

        workspace_id = session.execute(
            statement
        ).scalar_one_or_none()

        if workspace_id is None:
            workspace_id = session.scalar(
                select(Workspace.id).where(
                    Workspace.auth_issuer == auth_issuer,
                    Workspace.auth_user_id == auth_user_id,
                )
            )

        if workspace_id is None:
            raise RuntimeError("Workspace could not be resolved")

    return workspace_id