"""Real Gateway subprocess tests; discovery is passive and no device is opened."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / "tools"))

from mosaico_cli.errors import DeviceError, EnvironmentError
from mosaico_cli.runtime import RunContext
from mosaico_cli.session_runtime import SessionScope, request
from mosaico_cli.workspace import load_workspace


def workspace(tmp_path):
    for name in ("a", "b"):
        project = tmp_path / "projects" / name
        project.mkdir(parents=True)
        (project / "CMakeLists.txt").write_text("include($ENV{IDF_PATH}/tools/cmake/project.cmake)\nproject(test)\n")
    (tmp_path / ".mosaico.json").write_text(json.dumps({
        "schema_version": 1,
        "workspace": {"projects_dir": "projects", "default_project": "projects/a", "run_dir": ".runs"},
        "dependencies": {"bsp": "bsp", "esp_iris": str(TOOLS.parent / "ESP-Iris")},
        "build": {"runner": "builtin"},
        "devices": [{"id": "esp-mosaico", "target": "esp32s31"}],
    }))
    return load_workspace(TOOLS, start=tmp_path)


def scope(project, *, persistent=True):
    value = SessionScope()
    value.arguments = Namespace(project=str(project), command="session" if persistent else "list",
                                session_action="run" if persistent else None, device_id=None, endpoint=None)
    return value


def test_two_projects_reuse_and_creator_lifetime(tmp_path, monkeypatch):
    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    work = workspace(tmp_path)
    script = work.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    a, b, follower = scope(tmp_path / "projects/a"), scope(tmp_path / "projects/b"), scope(tmp_path / "projects/a")
    context = RunContext(work, "test", json_output=True)
    # This test exercises process/network lifetime, not ESP-IDF setup.
    with patch("mosaico_cli.runtime.resolve_idf_path", side_effect=EnvironmentError("no IDF needed")):
        try:
            first = a.gateway(context, Path(sys.executable), script, "test-revision")
            second = b.gateway(context, Path(sys.executable), script, "test-revision")
            same = follower.gateway(context, Path(sys.executable), script, "test-revision")
            assert first.connection_args != second.connection_args
            assert same.connection_args == first.connection_args
            assert first.started_local and not same.started_local
            incompatible = scope(tmp_path / "projects/a")
            with pytest.raises(EnvironmentError, match="revision"):
                incompatible.gateway(context, Path(sys.executable), script, "different-revision")
            assert not incompatible.processes
            unavailable = scope(tmp_path / "projects/a")
            with patch("mosaico_cli.session_runtime.request", side_effect=DeviceError("probe timed out")), \
                    pytest.raises(EnvironmentError, match="alive but unavailable"):
                unavailable.gateway(context, Path(sys.executable), script, "test-revision")
            assert not unavailable.processes
            assert a.processes[0][2].exists()
            follower.close()
            assert request(first.connection_args[1], "/v1/health")["ready"]
            assert request(first.connection_args[1], "/v1/devices")["devices"] == []
            a.close()
            assert request(second.connection_args[1], "/v1/health")["ready"]
        finally:
            a.close()
            b.close()
            follower.close()


def test_temporary_session_cannot_be_reused_and_connection_record_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    work = workspace(tmp_path)
    script = work.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    owner = scope(tmp_path / "projects/a", persistent=False)
    follower = scope(tmp_path / "projects/a")
    context = RunContext(work, "test", json_output=True)
    with patch("mosaico_cli.runtime.resolve_idf_path", side_effect=EnvironmentError("no IDF needed")):
        try:
            owner.gateway(context, Path(sys.executable), script, "test-revision")
            with pytest.raises(EnvironmentError, match="temporary command"):
                follower.gateway(context, Path(sys.executable), script, "test-revision")
            record = owner.processes[0][2]
            assert record.is_file()
        finally:
            owner.close()
            follower.close()
    assert not record.exists()


def test_public_list_handles_passive_discovery_without_connected_devices(tmp_path, monkeypatch, capsys):
    from mosaico_cli.cli import _print_device_table, main

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    work = workspace(tmp_path)
    script = work.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    with patch("mosaico_cli.gateway.ensure_iris_tools", return_value=(Path(sys.executable), script)), \
            patch("mosaico_cli.runtime.resolve_idf_path", side_effect=EnvironmentError("no IDF needed")):
        assert main(["--workspace", str(tmp_path), "list"], tool_root=TOOLS) == 0
    assert "DEVICE_ID" in capsys.readouterr().out
    assert not list((tmp_path / "state").rglob("connection.json"))
    _print_device_table({"devices": [], "endpoints": [{"endpoint": "tcp:127.0.0.1:1234"}]}, False)
    assert "Endpoint: tcp:127.0.0.1:1234" in capsys.readouterr().out


def test_follower_reads_committed_result_after_owner_exits(tmp_path, monkeypatch):
    from mosaico_cli.gateway import _wait_gateway_operation
    from mosaico_cli.session_runtime import CURRENT_SCOPE

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    work = workspace(tmp_path)
    script = work.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    owner, follower = scope(tmp_path / "projects/a"), scope(tmp_path / "projects/a")
    context = RunContext(work, "test", json_output=True)
    with patch("mosaico_cli.runtime.resolve_idf_path", side_effect=EnvironmentError("no IDF needed")):
        try:
            owner.gateway(context, Path(sys.executable), script, "test-revision")
            session = follower.gateway(context, Path(sys.executable), script, "test-revision")
            from iris_gateway.store import GatewayStore

            store = GatewayStore(owner.processes[0][2].parent / "state")
            try:
                accepted, _ = store.create_operation({
                    "operation_id": "finished-install", "device_id": "test-device",
                    "actor_type": "local", "actor_name": "test", "action": "firmware.ota",
                    "status": "queued", "created_ns": time.time_ns(),
                })
                store.update_operation("finished-install", status="succeeded", finished_ns=time.time_ns(),
                                       result_json={"healthy": True, "boot_id": 18446744073709551614})
            finally:
                store.close()
            # A live owner, even one with a terminal operation, must not be bypassed.
            assert follower.finished_operation(session, "finished-install") is None
            owner.close()
            token = CURRENT_SCOPE.set(follower)
            try:
                result = _wait_gateway_operation(context, session,
                    result=subprocess.CompletedProcess([], 0, json.dumps({"operation": accepted})),
                    started=time.monotonic(), timeout=15, action="Installation", progress_prefix="ota")
            finally:
                CURRENT_SCOPE.reset(token)
            assert result["operation"]["status"] == "succeeded"
            assert result["operation"]["result"]["healthy"] is True
            assert result["operation"]["result"]["boot_id_text"] == "18446744073709551614"
            assert not follower.processes  # No restarted Gateway and no replay.
        finally:
            owner.close()
            follower.close()


@pytest.mark.parametrize("status,created_ns,finished_ns,expected", [
    ("succeeded", 11, 12, True),
    ("failed", 11, 12, True),
    ("reconnecting", 11, None, False),
    ("succeeded", 9, 12, False),
    ("succeeded", 11, None, False),
])
def test_finished_operation_requires_this_session_and_terminal_evidence(
    tmp_path, monkeypatch, status, created_ns, finished_ns, expected,
):
    monkeypatch.syspath_prepend(str(TOOLS.parent / "ESP-Iris/components/esp_iris/tools"))
    from iris_gateway.store import GatewayStore

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / name)
    follower = SessionScope()
    session = object()
    follower.sessions["test-project"] = session
    follower.records["test-project"] = {"created_ns": 10}
    store = GatewayStore(tmp_path / "esp-mosaico/project-sessions/test-project/state")
    try:
        store.create_operation({"operation_id": "op", "device_id": "device", "actor_type": "local",
                                "actor_name": "test", "action": "firmware.ota", "status": status,
                                "created_ns": created_ns})
        store.update_operation("op", finished_ns=finished_ns)
    finally:
        store.close()
    assert (follower.finished_operation(session, "op") is not None) is expected
    assert follower.finished_operation(session, "missing") is None
    assert follower.finished_operation(object(), "op") is None


def test_status_without_gateway_does_not_bootstrap_or_spawn(tmp_path, monkeypatch, capsys):
    from mosaico_cli.cli import main

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    workspace(tmp_path)
    monkeypatch.setattr("mosaico_cli.gateway._pinned_source_revision", lambda path: "test-revision")
    with patch("mosaico_cli.gateway.ensure_iris_tools") as bootstrap, \
            patch("mosaico_cli.session_runtime.subprocess.Popen") as spawn:
        assert main(["--workspace", str(tmp_path), "iris", "status", "--json"], tool_root=TOOLS) == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "session": None}
    bootstrap.assert_not_called()
    spawn.assert_not_called()
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("action", [
    ["claim", "--endpoint", "usb:location=1-2"],
    ["release", "--device-id", "board"],
    ["reconcile", "--device-id", "board"],
    ["transfer", "start", "--device-id", "board", "--to-session", "other"],
    ["transfer", "status", "--transfer-id", "t"],
])
def test_ownership_without_gateway_fails_without_creating_one(tmp_path, monkeypatch, capsys, action):
    from mosaico_cli.cli import main

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    workspace(tmp_path)
    monkeypatch.setattr("mosaico_cli.gateway._pinned_source_revision", lambda path: "test-revision")
    with patch("mosaico_cli.gateway.ensure_iris_tools") as bootstrap, \
            patch("mosaico_cli.session_runtime.subprocess.Popen") as spawn:
        assert main(["--workspace", str(tmp_path), "iris", *action, "--json"], tool_root=TOOLS) == 4
    assert json.loads(capsys.readouterr().err)["error"] == "gateway_not_running"
    bootstrap.assert_not_called()
    spawn.assert_not_called()


@pytest.mark.parametrize("persistent", [True, False])
def test_status_observes_live_gateway_without_taking_its_lifetime(tmp_path, monkeypatch, capsys, persistent):
    from mosaico_cli.cli import main

    monkeypatch.setattr("mosaico_cli.session_runtime.state_root", lambda name: tmp_path / "state" / name)
    work = workspace(tmp_path)
    script = work.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    owner = scope(tmp_path / "projects/a", persistent=persistent)
    with patch("mosaico_cli.runtime.resolve_idf_path", side_effect=EnvironmentError("no IDF needed")), \
            patch("mosaico_cli.gateway._pinned_source_revision", return_value="test-revision"):
        try:
            session = owner.gateway(RunContext(work, "test", json_output=True), Path(sys.executable), script, "test-revision")
            with patch("mosaico_cli.gateway.ensure_iris_tools") as bootstrap, \
                    patch("mosaico_cli.session_runtime.subprocess.Popen") as spawn:
                assert main(["--workspace", str(tmp_path), "iris", "status", "--json"], tool_root=TOOLS) == 0
            state = json.loads(capsys.readouterr().out)
            assert state["running"] is True
            assert state["session"]["persistent"] == persistent
            bootstrap.assert_not_called()
            spawn.assert_not_called()
            assert owner.processes[0][0].poll() is None
            assert request(session.connection_args[1], "/v1/health")["project_session"]["session_id"] == state["session"]["session_id"]
        finally:
            owner.close()
        # A stopped session's retained state also must not trigger startup.
        with patch("mosaico_cli.session_runtime.subprocess.Popen") as spawn:
            assert main(["--workspace", str(tmp_path), "iris", "status", "--json"], tool_root=TOOLS) == 0
        assert json.loads(capsys.readouterr().out)["running"] is False
        spawn.assert_not_called()
