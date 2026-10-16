"""Download and register the demo corpus and create its job; no AI requests."""

from pathlib import Path
import subprocess
import sys


def main():
    backend = Path(__file__).resolve().parents[1]
    for module in ("scripts.download_dataset", "scripts.seed_images", "scripts.create_batch_job"):
        subprocess.run([sys.executable, "-m", module], cwd=backend, check=True)


if __name__ == "__main__":
    main()
