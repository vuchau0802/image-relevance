"""Shared filesystem checks for registered corpus images."""

import hashlib

from app.config import PROJECT_ROOT


def verify_registered_image(file_path: str, checksum: str):
    path = (PROJECT_ROOT / file_path).resolve()
    corpus = (PROJECT_ROOT / "data" / "images").resolve()
    if not path.is_relative_to(corpus):
        raise ValueError("Image path is outside the corpus folder")
    if not path.is_file():
        raise ValueError("Registered image file is missing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError("Image file differs from its registered checksum")
    return path
