"""One-command local API startup after installing dependencies and configuring .env."""

from pathlib import Path
import subprocess
import sys


def main():
    backend = Path(__file__).resolve().parents[1]
    project = backend.parent
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "db"], cwd=project, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, check=True)
    subprocess.run([
        sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
    ], cwd=backend, check=True)


if __name__ == "__main__":
    main()
