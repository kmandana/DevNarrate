"""Shared test fixtures for DevNarrate tests."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit.

    Returns the path to the repo root.
    """
    subprocess.run(
        ["git", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@devnarrate.test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    # Create an initial commit so we have a valid HEAD
    initial_file = tmp_path / "README.md"
    initial_file.write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path
