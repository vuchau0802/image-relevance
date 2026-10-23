"""Filesystem checks for registered demo and workspace images."""

import hashlib
import re

from app.config import PROJECT_ROOT


def verify_registered_image(
    file_path: str,
    checksum: str,
    tenant_id: str | None = None,
):
    project = PROJECT_ROOT.resolve()
    path = (project / file_path).resolve()
    corpus = (project / "data" / "images").resolve()

    allowed = (
        corpus.is_relative_to(project)
        and path.is_relative_to(corpus)
    )

    if (
        isinstance(tenant_id, str)
        and re.fullmatch(r"ws_[0-9a-f]{32}", tenant_id)
    ):
        workspace = (
            project / "data" / "uploads" / tenant_id
        ).resolve()

        allowed = allowed or (
            workspace.is_relative_to(project)
            and path.is_relative_to(workspace)
        )

    if not allowed:
        raise ValueError("Image path is outside permitted storage")

    if not path.is_file():
        raise ValueError("Registered image file is missing")

    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError(
            "Image file differs from its registered checksum"
        )

    return path