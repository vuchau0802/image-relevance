from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import AuthenticatedUser, require_user
from app.repositories.workspaces import get_or_create_workspace

router = APIRouter(tags=["account"])


class CurrentUserResponse(BaseModel):
    user_id: str


@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> CurrentUserResponse:
    return CurrentUserResponse(user_id=user.user_id)

class CurrentWorkspaceResponse(BaseModel):
    workspace_id: str


@router.post(
    "/workspace",
    response_model=CurrentWorkspaceResponse,
)
def initialize_workspace(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> CurrentWorkspaceResponse:
    workspace_id = get_or_create_workspace(
        auth_issuer=user.issuer,
        auth_user_id=user.user_id,
    )

    return CurrentWorkspaceResponse(
        workspace_id=workspace_id,
    )