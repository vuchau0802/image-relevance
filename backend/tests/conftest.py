"""Tests never inherit the demo database or real API credentials."""

import os

import pytest
from sqlalchemy import make_url


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False)


def pytest_configure(config):
    os.environ.update({
        "GEMINI_API_KEY": "unused-test-key", "VISION_MODEL": "test-model",
        "VISION_DAILY_CALL_LIMIT": "40", "MIN_CLASSIFICATION_CONFIDENCE": "0.70",
    })
    if config.getoption("--run-integration"):
        value = os.environ.get("TEST_DATABASE_URL")
        if not value:
            raise pytest.UsageError("Set TEST_DATABASE_URL or use scripts.run_integration_tests")
        url = make_url(value)
        if url.get_backend_name() != "postgresql" or not url.database or not url.database.endswith("_test"):
            raise pytest.UsageError("Integration tests require a PostgreSQL database ending in _test")
        os.environ.update({
            "POSTGRES_HOST": url.host or "127.0.0.1",
            "POSTGRES_PORT": str(url.port or 5432), "POSTGRES_USER": url.username or "",
            "POSTGRES_PASSWORD": url.password or "", "POSTGRES_DB": url.database,
        })
    else:
        os.environ.update({
            "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "1",
            "POSTGRES_USER": "unit_test", "POSTGRES_PASSWORD": "unused-test-password",
            "POSTGRES_DB": "unit_test",
        })


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="Use scripts.run_integration_tests for isolated PostgreSQL checks")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
