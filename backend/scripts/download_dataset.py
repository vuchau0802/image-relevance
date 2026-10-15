"""Restore the pinned original corpus without API keys or a database."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.request import Request, urlopen
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHUNK_SIZE = 1024 * 1024


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path):
    dataset = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    archive = dataset["archive"]
    if not archive["url"].startswith("https://github.com/"):
        raise ValueError("Dataset URL must use HTTPS on github.com")
    if not re.fullmatch(r"[0-9a-f]{64}", archive["sha256"]):
        raise ValueError("Invalid archive SHA-256")
    if not isinstance(archive["size_bytes"], int) or archive["size_bytes"] <= 0:
        raise ValueError("Invalid archive size")
    filenames = set()
    for entry in dataset["files"]:
        filename = entry["filename"]
        if not re.fullmatch(r"img_[0-9]{3}\.jpg", filename):
            raise ValueError("Invalid dataset filename")
        if filename in filenames:
            raise ValueError("Duplicate dataset filename")
        filenames.add(filename)
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid image SHA-256")
        if not isinstance(entry["size_bytes"], int) or entry["size_bytes"] <= 0:
            raise ValueError("Invalid image size")
    if not filenames:
        raise ValueError("Dataset file inventory is empty")
    return dataset


def verify_image(path, entry):
    if path.is_symlink():
        raise ValueError(f"Refusing image symlink: {entry['filename']}")
    if not path.is_file():
        raise ValueError(f"Missing image: {entry['filename']}")
    if (
        path.stat().st_size != entry["size_bytes"]
        or sha256_file(path) != entry["sha256"]
    ):
        raise ValueError(f"Image checksum mismatch: {entry['filename']}")


def verify_existing(dataset, destination):
    for entry in dataset["files"]:
        verify_image(destination / entry["filename"], entry)


def download_archive(archive, destination):
    request = Request(archive["url"], headers={"User-Agent": "image-relevance-dataset/1"})
    downloaded = 0
    with urlopen(request, timeout=60) as response, destination.open("xb") as output:
        while chunk := response.read(CHUNK_SIZE):
            downloaded += len(chunk)
            if downloaded > archive["size_bytes"]:
                raise ValueError("Download exceeds pinned archive size")
            output.write(chunk)


def install_archive(archive_path, dataset, destination):
    archive_path = Path(archive_path)
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("Refusing a symlink as the image destination")
    if (
        archive_path.stat().st_size != dataset["archive"]["size_bytes"]
        or sha256_file(archive_path) != dataset["archive"]["sha256"]
    ):
        raise ValueError("Archive size or SHA-256 mismatch")

    # Check existing images before creating or copying any dataset files.
    for entry in dataset["files"]:
        path = destination / entry["filename"]
        if path.exists() or path.is_symlink():
            verify_image(path, entry)

    expected = {f"images/{entry['filename']}": entry for entry in dataset["files"]}
    with zipfile.ZipFile(archive_path) as archive:
        members = {}
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            if member.is_dir() and name == "images/":
                continue
            if (
                name not in expected
                or name in members
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or (member.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError(f"Unexpected or unsafe archive member: {name}")
            if member.file_size != expected[name]["size_bytes"]:
                raise ValueError(f"Archived image size mismatch: {name}")
            members[name] = member
        if members.keys() != expected.keys():
            raise ValueError("Archive does not contain the complete pinned corpus")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dataset-stage-", dir=destination.parent) as staging:
            staging = Path(staging)
            # Validate every archive image before installing any of them.
            for name, entry in expected.items():
                staged_file = staging / entry["filename"]
                with archive.open(members[name]) as source, staged_file.open("xb") as output:
                    shutil.copyfileobj(source, output, CHUNK_SIZE)
                verify_image(staged_file, entry)

            destination.mkdir(exist_ok=True)
            installed = 0
            for entry in dataset["files"]:
                target = destination / entry["filename"]
                try:
                    # Same-volume hard links install complete files atomically
                    # and refuse to replace any concurrently created target.
                    os.link(staging / entry["filename"], target)
                    installed += 1
                except FileExistsError:
                    verify_image(target, entry)
    verify_existing(dataset, destination)
    return installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--archive", type=Path, help="Use a local ZIP instead of downloading")
    options.add_argument("--verify-only", action="store_true", help="Check existing images without downloading")
    parser.add_argument("--destination", type=Path, default=PROJECT_ROOT / "data" / "images")
    args = parser.parse_args()
    dataset = load_dataset(PROJECT_ROOT / "data" / "dataset.json")

    if args.verify_only:
        verify_existing(dataset, args.destination)
        print(f"Verified {len(dataset['files'])} original images; no files changed.")
        return

    if args.archive:
        installed = install_archive(args.archive, dataset, args.destination)
    else:
        with tempfile.TemporaryDirectory(prefix="image-relevance-download-") as staging:
            archive_path = Path(staging) / "dataset.zip"
            print("Downloading pinned dataset release asset...")
            download_archive(dataset["archive"], archive_path)
            installed = install_archive(archive_path, dataset, args.destination)
    print(f"Verified {len(dataset['files'])} images; installed {installed} missing files.")


if __name__ == "__main__":
    main()
