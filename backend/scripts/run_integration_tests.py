"""Migrate and test an explicitly isolated PostgreSQL database; no Gemini calls."""

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import make_url


def main():
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://image_relevance_test:local_test_only@127.0.0.1:55432/image_relevance_test",
    )
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not url.database or not url.database.endswith("_test"):
        raise ValueError("Refusing a database that is not PostgreSQL with a name ending _test")
    env = os.environ.copy()
    env.update({
        "TEST_DATABASE_URL": value,
        "POSTGRES_HOST": url.host or "127.0.0.1", "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_USER": url.username or "", "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": url.database,
        "GEMINI_API_KEY": "unused-test-key", "VISION_MODEL": "test-model",
    })
    backend = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env, check=True)
    subprocess.run([
        sys.executable, "-m", "pytest", "tests", "--run-integration", "-q", "--tb=short",
    ], cwd=backend, env=env, check=True)


if __name__ == "__main__":
    main()
