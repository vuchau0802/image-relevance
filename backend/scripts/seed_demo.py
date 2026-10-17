"""Prepare the matching demo; preserve progress between runs."""

from pathlib import Path
import subprocess
import sys


def main():
    backend = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.prepare_demo",
            *sys.argv[1:],
        ],
        cwd=backend,
        check=False,
    )

    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()