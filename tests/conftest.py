"""Pytest configuration and fixtures."""

import pytest
import tempfile
import shutil
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line("markers", "legacy: tests that depend on SQLite (skipped after migration)")


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp)


@pytest.fixture
def mock_db_path(temp_dir):
    """Provide a temporary database path."""
    return temp_dir / "test_assessment.db"
