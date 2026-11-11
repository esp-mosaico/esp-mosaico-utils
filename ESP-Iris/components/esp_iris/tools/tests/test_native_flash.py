from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from test_host_operations import HostHub

from iris_gateway.client import prepare_native_flash
from iris_gateway.gateway import GatewayService
from iris_gateway.host_worker import publish_request
from iris_gateway.hub import IrisHub
from iris_gateway.security import Actor
from iris_gateway.store import GatewayStore


def flash_request(tmp_path, target="flash"):
    return prepare_native_flash(tmp_path, {"argv": ["idf.py", "-p", "{port}", target]},
                                target=target, endpoint="usb:location=host-operation-test",
                                reconnect_timeout=0)


@pytest.mark.parametrize("target", ["flash", "app-flash"])
def test_native_command_needs_no_build_outputs(tmp_path, target):
    request = flash_request(tmp_path, target)
    assert request["commands"][0]["argv"] == ["idf.py", "-p", "{port}", target]
    assert list(tmp_path.iterdir()) == []


def test_native_console_baud_is_independent_of_build_metadata(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/sdkconfig.json").write_text("invalid stale configuration")
    request = prepare_native_flash(tmp_path, {"argv": ["idf.py", "flash"]}, endpoint="/dev/fake",
                                   baudrate=74880)
    assert request["baudrate"] == 74880


@pytest.mark.parametrize("returncode", [0, 7])
def test_worker_runs_native_command_without_image_checks(tmp_path, monkeypatch, returncode):
    import subprocess
    import uuid

    from iris_gateway import host_worker

    request = flash_request(tmp_path)
    location = str(uuid.uuid4())
    endpoint = "usb:location=" + location
    monkeypatch.setattr(host_worker, "resolve_usb_port", lambda _: {"device_path": "fake", "location": location})
    with patch("iris_gateway.host_worker.subprocess.run", return_value=subprocess.CompletedProcess([], returncode)) as execute:
        spec = {**request, "operation_id": location, "resources": [endpoint],
                "endpoints": [], "locks": [endpoint], "write_endpoint": endpoint,
                "log_path": str(tmp_path / "output.log")}
        if returncode:
            with pytest.raises(subprocess.CalledProcessError) as error:
                host_worker.run(spec)
            assert error.value.returncode == returncode
        else:
            assert host_worker.run(spec)["returncode"] == 0
        assert execute.call_args.args[0] == ["idf.py", "-p", "fake", "flash"]


@pytest.mark.parametrize("connected,outcome", [
    (True, "connected"), (True, "waiting"), (False, "connected"),
    (False, "waiting"), (True, "image_mismatch"), (True, "identity_mismatch"),
    (True, "resume_error"), (True, "failed"),
])
def test_flash_does_not_require_old_firmware_and_separates_connection(tmp_path, connected, outcome):
    async def scenario():
        store = GatewayStore(tmp_path / "store")
        service = GatewayService(store, instance_id="native-flash-test")
        hub = HostHub()
        hub.connected = connected
        hub.configure_host_console = lambda endpoint, **kwargs: None
        hub.status = AsyncMock(side_effect=TimeoutError("old application hung"))
        hub.crash_report = AsyncMock(side_effect=TimeoutError("old application hung"))
        service.attach_hub(hub)
        original_resume = hub.resume_after_host

        async def resume(endpoint, **kwargs):
            if outcome == "resume_error":
                raise OSError("port disappeared")
            reset = kwargs.pop("reset", False)
            await original_resume(endpoint, **kwargs)
            if reset:
                hub.actions.append("startup_reset")
            hub.connected = outcome != "waiting"
            if outcome == "identity_mismatch":
                hub.info["device_id"] = "other-board"
            return {"state": "sequence_completed", "reader_started_before_reset": True} if reset else None

        hub.resume_after_host = resume
        hub.list_endpoints = lambda: [{"endpoint": hub.endpoint, "device_id": hub.info["device_id"],
                                       "state": "ready" if hub.connected else "waiting"}]

        class Process:
            def __init__(self):
                self.stdin = self

            def write(self, data):
                self.spec = json.loads(data)

            async def drain(self):
                pass

            def close(self):
                pass

            async def wait(self):
                assert not hub.connected
                assert "resume" not in hub.actions
                hub.actions.append("writer_exit")
                hub.info.update(boot_id=2, firmware_mode="normal", capability_names=[],
                                project_name="esp-iris-template", firmware_sha256="00" * 32)
                if outcome == "image_mismatch":
                    hub.info["project_name"] = "other-app"
                Path(self.spec["log_path"]).write_text("Writing at 0x10000 (100 %)\n")
                Path(self.spec["result_path"]).write_text(json.dumps({
                    "returncode": 1 if outcome == "failed" else 0, "stdout": "written", "error": "writer failed"}))
                return 0

        spec = flash_request(tmp_path)
        try:
            with patch("iris_gateway.host_operations.asyncio.create_subprocess_exec", AsyncMock(return_value=Process())):
                operation = await service.host_operations.submit(publish_request(spec), Actor("local", "test"))
                while service.operations._pending:
                    await asyncio.sleep(0.01)
            operation = store.operation(operation["operation_id"])
            assert operation["status"] == ("failed" if outcome == "failed" else "succeeded"), operation
            if outcome != "failed":
                evidence = operation["result"]["evidence"]
                assert evidence["write_completed"]
                assert evidence["connection"]["state"] == ("unavailable" if outcome == "resume_error" else
                                                             "connected" if outcome == "image_mismatch" else outcome)
            hub.status.assert_not_called()
            hub.crash_report.assert_not_called()
            if "resume" in hub.actions:
                assert hub.actions.index("writer_exit") < hub.actions.index("resume")
            assert "startup_reset" not in hub.actions
            if outcome == "failed":
                assert operation["progress"]["native_returncode"] == 1
            assert not service.operations._exclusive
        finally:
            await service.operations.close()
            store.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("vid,pid,uart", [(0x10c4, 0xea60, True), (0x303a, 0x1001, False)])
def test_native_flash_resumes_explicit_uart_and_jtag_without_hello(vid, pid, uart):
    async def scenario():
        hub = IrisHub("test")
        endpoint = "usb:location=native-test"
        metadata = {"vid": vid, "pid": pid, "link_role": "control", "endpoint": endpoint,
                    "location": "native-test", "path": "/dev/fake"}
        hub._endpoint_states[endpoint] = {**metadata, "resume_after_host": False}
        hub._endpoint_configs[endpoint] = (AsyncMock(), None)
        hub._host_endpoints.add(endpoint)
        hub.configure_host_console(endpoint, baudrate=74880)
        with patch("iris_gateway.hub.resolve_usb_port", return_value=metadata), patch.object(hub, "_add_supervisor") as start:
            await hub.resume_after_host(endpoint, connect=True)
            start.assert_called_once()
        assert hub._endpoint_states[endpoint]["uart"] == uart
        assert hub._endpoint_states[endpoint]["baudrate"] == 74880
        assert endpoint not in hub._host_endpoints
        await hub.close()

    asyncio.run(scenario())


def test_native_flash_rejects_application_usb():
    hub = IrisHub("test")
    endpoint = "usb:hs"
    hub._endpoint_states[endpoint] = {"endpoint": endpoint, "vid": 0x303a, "pid": 0x4002}
    with pytest.raises(ValueError, match="UART or USB Serial/JTAG"):
        hub.configure_host_console(endpoint)


@pytest.mark.parametrize("write_result", [0, 1, None])
def test_native_flash_restart_reconciliation_never_replays_or_requires_iris(tmp_path, write_result):
    from iris_gateway.cli import _recover_interrupted

    async def scenario():
        store = GatewayStore(tmp_path / "store")
        endpoint = "usb:location=host-operation-test"
        store.create_operation({"operation_id": "flash", "device_id": "endpoint::" + endpoint,
                                "actor_type": "local", "actor_name": "test", "action": "host.flash",
                                "params": {"endpoints": [{"endpoint": endpoint}]},
                                "status": "transferring", "created_ns": 1})
        folder = store.artifacts_dir / "host-operations/flash"
        folder.mkdir(parents=True)
        (folder / "before.json").write_text("{}")
        if write_result is not None:
            (folder / "result.json").write_text(json.dumps({"returncode": write_result}))
        _recover_interrupted(store)
        original = store.operation("flash")
        assert original["status"] == "outcome_unknown"
        service = GatewayService(store, instance_id="restarted")
        hub = HostHub()
        hub.connected = False
        service.attach_hub(hub)
        try:
            with patch("iris_gateway.host_operations.asyncio.create_subprocess_exec", side_effect=AssertionError("write replay")):
                record = await service.host_operations.reconcile("flash", Actor("local", "test"))
            assert record["outcome"] == ("observed_success" if write_result == 0 else "outcome_unknown")
            if write_result == 0:
                assert record["evidence"] == {"write_completed": True, "connection": {"state": "waiting", "endpoint": endpoint}}
            assert not record["replayed"]
            assert store.operation("flash") == original
            assert not hub.actions
        finally:
            await service.operations.close()
            store.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("returncode", [0, 7])
def test_native_worker_persists_real_process_result_without_build_metadata(tmp_path, monkeypatch, returncode):
    import io
    import sys
    import uuid

    from iris_gateway import host_worker

    location = str(uuid.uuid4())
    endpoint = "usb:location=" + location
    result_path = tmp_path / "result.json"
    artifact = tmp_path / "built.bin"
    script = ("from pathlib import Path; import sys; "
              "Path(sys.argv[1]).write_bytes(b'IDF owns build outputs'); "
              "print('native output', sys.argv[2]); sys.exit(int(sys.argv[3]))")
    request = prepare_native_flash(tmp_path / "missing-build", {
        "argv": [sys.executable, "-c", script, str(artifact), "{port}", str(returncode)],
    }, endpoint=endpoint)
    spec = {**request, "operation_id": location, "resources": [endpoint], "endpoints": [],
            "locks": [endpoint], "write_endpoint": endpoint, "log_path": str(tmp_path / "output.log"),
            "result_path": str(result_path)}
    monkeypatch.setattr(host_worker, "resolve_usb_port", lambda _: {"device_path": "fake", "location": location})
    monkeypatch.setattr(host_worker.sys, "stdin", io.StringIO(json.dumps(spec)))
    with patch("iris_gateway.host_worker.signal.signal"):
        host_worker.main()
    result = json.loads(result_path.read_text())
    assert result["returncode"] == returncode
    assert result["stdout"].splitlines() == ["native output fake"]
    assert artifact.read_bytes() == b"IDF owns build outputs"
