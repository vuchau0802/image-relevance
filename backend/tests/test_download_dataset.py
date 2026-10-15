import hashlib
from pathlib import Path
import zipfile

import pytest

from scripts.download_dataset import install_archive, sha256_file


def make_dataset(tmp_path, *, member="images/img_001.jpg", expected_payload=None):
    payload = b"original-image-bytes"
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(member, payload)
    expected_payload = payload if expected_payload is None else expected_payload
    dataset = {
        "archive": {
            "size_bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
        },
        "files": [{
            "filename": "img_001.jpg",
            "size_bytes": len(expected_payload),
            "sha256": hashlib.sha256(expected_payload).hexdigest(),
        }],
    }
    return archive, dataset, payload


def test_archive_restores_exact_bytes_and_preserves_existing_file(tmp_path):
    archive, dataset, payload = make_dataset(tmp_path)
    destination = tmp_path / "corpus"

    assert install_archive(archive, dataset, destination) == 1
    image = destination / "img_001.jpg"
    assert image.read_bytes() == payload
    original_stat = image.stat()

    assert install_archive(archive, dataset, destination) == 0
    assert image.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert image.stat().st_ino == original_stat.st_ino


def test_wrong_archive_hash_is_rejected_before_installation(tmp_path):
    archive, dataset, _ = make_dataset(tmp_path)
    dataset["archive"]["sha256"] = "0" * 64
    destination = tmp_path / "corpus"

    with pytest.raises(ValueError, match="Archive size or SHA-256 mismatch"):
        install_archive(archive, dataset, destination)
    assert not destination.exists()


def test_changed_existing_image_is_never_overwritten(tmp_path):
    archive, dataset, _ = make_dataset(tmp_path)
    destination = tmp_path / "corpus"
    destination.mkdir()
    image = destination / "img_001.jpg"
    image.write_bytes(b"locally-modified-image")

    with pytest.raises(ValueError, match="Image checksum mismatch"):
        install_archive(archive, dataset, destination)
    assert image.read_bytes() == b"locally-modified-image"


def test_archive_path_traversal_is_rejected(tmp_path):
    archive, dataset, _ = make_dataset(tmp_path, member="images/../../escaped.jpg")
    destination = tmp_path / "corpus"

    with pytest.raises(ValueError, match="Unexpected or unsafe archive member"):
        install_archive(archive, dataset, destination)
    assert not destination.exists()
    assert not (tmp_path / "escaped.jpg").exists()


def test_inner_image_hash_mismatch_installs_nothing(tmp_path):
    archive, dataset, _ = make_dataset(tmp_path)
    dataset["files"][0]["sha256"] = "f" * 64
    destination = tmp_path / "corpus"

    with pytest.raises(ValueError, match="Image checksum mismatch"):
        install_archive(archive, dataset, destination)
    assert not destination.exists()
