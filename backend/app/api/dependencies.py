from typing import Annotated

from fastapi import Depends

from app.repositories.workspaces import get_or_create_workspace
from app.services.auth import AuthenticatedUser, require_user


def require_workspace(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> str:
    return get_or_create_workspace(
        auth_issuer=user.issuer,
        auth_user_id=user.user_id,
    )


CurrentWorkspace = Annotated[str, Depends(require_workspace)]