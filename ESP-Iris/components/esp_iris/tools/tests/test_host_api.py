"""Consumer-facing host API must not depend on server imports or mutate queries."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from iris_gateway.client import LocalProject, LocalStateError, registry_snapshot
from iris_gateway.ownership import OwnershipRegistry
from iris_gateway.source_identity import source_identity


def test_public_api_imports_without_site_packages(tmp_path):
    tools = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-S", "-c", "from iris_gateway import client; assert client.API_MAJOR == 1"],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tools)}, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_absent_state_queries_create_nothing(tmp_path):
    state = tmp_path / "absent"
    local = LocalProject(state, tmp_path, tmp_path / "app")
    assert registry_snapshot(state)["sessions"] == []
    assert not local.running()
    assert local.finished_operation({"project_id": local.project_id, "created_ns": 1}, "op") is None
    assert not state.exists()


@pytest.mark.parametrize("version", [0, 2])
def test_registry_reader_rejects_unknown_schema_without_migration(tmp_path, version):
    root = tmp_path / "ownership"
    root.mkdir()
    path = root / "ownership.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={version}")
    original = path.read_bytes()
    with pytest.raises(LocalStateError, match="Unsupported"):
        registry_snapshot(tmp_path)
    assert path.read_bytes() == original


def test_registry_reader_accepts_legacy_metadata_and_observes_lock_liveness(tmp_path):
    registry = OwnershipRegistry(tmp_path / "ownership")
    try:
        registry.register("session", "project", "/workspace/app", "instance")
        registry.db.execute("DROP TABLE session_metadata")
        registry.db.commit()
        before = registry_snapshot(tmp_path)
        assert before["sessions"][0]["alive"] is True
        assert "workspace_path" not in before["sessions"][0]
    finally:
        registry.close()
    assert registry_snapshot(tmp_path)["sessions"][0]["alive"] is False


def test_source_fingerprint_is_scoped_and_detects_uncommitted_runtime_changes(tmp_path):
    iris = tmp_path / "ESP-Iris"
    tools = iris / "components/esp_iris/tools"
    (tools / "iris_gateway").mkdir(parents=True)
    code = tools / "iris_gateway/gateway.py"
    code.write_text("version = 1\n")
    first = source_identity(iris)
    (tmp_path / "recovery.c").write_text("unrelated product change")
    assert source_identity(iris)["fingerprint"] == first["fingerprint"]
    code.write_text("version = 2\n")
    second = source_identity(iris)
    assert second["fingerprint"] != first["fingerprint"]
    (tools / "rpc_catalog.json").write_text("{}")
    assert source_identity(iris)["fingerprint"] != second["fingerprint"]
