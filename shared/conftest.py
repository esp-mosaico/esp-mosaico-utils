"""Shared imports and isolated source copies without build/download caches."""
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))


@pytest.fixture
def standalone_shared(tmp_path):
    destination = tmp_path / "isolated modules/shared"
    shutil.copytree(ROOT, destination, ignore=shutil.ignore_patterns(
        "tests", "conftest.py", "__pycache__", ".cache", ".pytest_cache",
        ".codex-runs", "build*", "managed_components", "node_modules"))
    return destination
