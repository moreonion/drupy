"""Fixtures for the tests."""

import shutil
import tempfile

import pytest


@pytest.fixture(name="temp_dir")
def fixture_temp_dir():
    """Create a temporary directory and delete it after the test has run."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)
