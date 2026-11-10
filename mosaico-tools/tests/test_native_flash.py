from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mosaico_cli import native_flash
from mosaico_cli.cli import _normalize_globals, build_parser
from mosaico_cli.errors import NativeFlashError, OutcomeUnknownError


@pytest.mark.parametrize("target", ["flash", "app-flash"])
@pytest.mark.parametrize("follow", [False, True])
@pytest.mark.parametrize("extra", [[], ["--", "-b", "460800", "-D", "SDKCONFIG_DEFAULTS=custom.defaults"]])
def test_product_flash_prepares_before_handoff_and_does_not_require_hello(tmp_path, monkeypatch, target, follow, extra):
    spec = {"action": "host.flash"}
    events = []
    session = object()
    context = SimpleNamespace(workspace=object(), status=Mock(), json_output=False)
    arguments = build_parser().parse_args(["iris", target, "--endpoint", "/dev/ttyUSB0", "--baudrate", "74880",
                                           *(["--monitor"] if follow else []), *extra])
    monitor = Mock(return_value=0)
    monkeypatch.setattr("mosaico_cli.commands.monitor", monitor)
    prepare = Mock(return_value=spec)
    native = {"argv": ["idf.py", target], "env": {"ESPPORT": "{port}"}}

    def execute(context, selected, request, **kwargs):
        assert events == []
        assert selected is session
        assert request is spec
        events.append("flash")
        return {"operation_id": "flash-1", "endpoint": "usb:location=selected",
                "evidence": {"write_completed": True, "connection": {"state": "waiting"}}}

    for name, replacement in {
        "resolve_project": Mock(return_value=tmp_path),
        "resolve_idf_path": Mock(return_value=Path("/idf")),
        "idf_target_command": Mock(return_value=native),
        "ensure_gateway": Mock(return_value=session),
        "connected_devices": Mock(side_effect=AssertionError("must not require HELLO")),
        "host_api": Mock(return_value=SimpleNamespace(prepare_native_flash=prepare)),
        "run_host_operation": execute,
    }.items():
        monkeypatch.setattr(native_flash, name, replacement)
    result = native_flash.flash_application(arguments, context)
    assert result["status"] == "succeeded"
    assert result["evidence"]["connection"]["state"] == "waiting"
    assert prepare.call_args.args[1]["argv"] == ["idf.py", *extra[1:], target]
    assert not (tmp_path / "build").exists()
    assert prepare.call_args.kwargs["target"] == target
    assert prepare.call_args.kwargs["baudrate"] == 74880
    assert prepare.call_args.kwargs["reconnect_timeout"] == (0 if follow else 10)
    assert monitor.call_count == int(follow)
    if follow:
        assert monitor.call_args.kwargs == {"session": session, "endpoint": "usb:location=selected"}
    native_flash.ensure_gateway.assert_called_once_with(context, None, select=False)
    native_flash.idf_target_command.assert_called_once_with(
        context, idf_path=Path("/idf"), project=tmp_path, build_dir=tmp_path / "build",
        target=target, port="{port}", timeout=600)


def test_native_flash_incomplete_observation_does_not_request_vibe_acceptance(tmp_path, monkeypatch):
    from mosaico_cli import gateway

    context = SimpleNamespace(directory=tmp_path, status=Mock())
    session = gateway.GatewaySession(Path("python"), Path("iris"), ("--url", "http://127.0.0.1:8443"), None, False)
    operation = {"operation_id": "native-1", "status": "outcome_unknown", "progress": {"write_completed": True}}
    monkeypatch.setattr(gateway, "gateway_json", Mock(side_effect=[
        {"capabilities": ["local-host-operations/v1", "native-flash/v1"]}, {"operation": operation},
    ]))
    with pytest.raises(OutcomeUnknownError, match="connection observation") as error:
        gateway.run_host_operation(context, session, {"action": "host.flash"}, timeout=1)
    assert "Vibe Mode" not in str(error.value)
    assert "operation-reconcile native-1" in str(error.value)


@pytest.mark.parametrize("target", ["flash", "app-flash"])
def test_native_arguments_are_not_consumed_as_wrapper_options(target):
    args = build_parser().parse_args(_normalize_globals([
        "iris", target, "--endpoint", "/dev/ttyUSB0", "--", "--verbose", "-b", "460800",
        "-D", "SDKCONFIG_DEFAULTS=custom.defaults",
    ]))
    assert not args.verbose
    assert args.idf_args == ["--", "--verbose", "-b", "460800", "-D", "SDKCONFIG_DEFAULTS=custom.defaults"]


@pytest.mark.parametrize("target", ["flash", "app-flash"])
@pytest.mark.parametrize("launch_fails", [False, True])
def test_native_flash_can_explicitly_run_vibe_application(tmp_path, monkeypatch, target, launch_fails):
    arguments = build_parser().parse_args([
        "iris", target, "--endpoint", "/dev/ttyUSB0", "--run-app",
    ])
    context = SimpleNamespace(workspace=object(), status=Mock())
    calls = []

    def write(*args, **kwargs):
        calls.append("write")
        return {"endpoint": "/dev/ttyUSB0", "evidence": {"write_completed": True}}

    def launch(args, ctx, *, allow_running):
        assert calls == ["write"] and args.endpoint == "/dev/ttyUSB0" and allow_running
        calls.append("run")
        if launch_fails:
            raise OutcomeUnknownError("Application has not reconnected")
        return {"status": "succeeded", "boot_id": 2}

    for name, replacement in {
        "resolve_project": Mock(return_value=tmp_path),
        "resolve_idf_path": Mock(return_value=Path("/idf")),
        "idf_target_command": Mock(return_value={"argv": ["idf.py", target]}),
        "ensure_gateway": Mock(return_value=object()),
        "host_api": Mock(return_value=SimpleNamespace(prepare_native_flash=Mock(return_value={}))),
        "run_host_operation": write,
    }.items():
        monkeypatch.setattr(native_flash, name, replacement)
    monkeypatch.setattr("mosaico_cli.run_app.run_application", launch)
    if launch_fails:
        with pytest.raises(OutcomeUnknownError) as error:
            native_flash.flash_application(arguments, context)
        assert calls == ["write", "run"]
        assert error.value.details["flash_write_completed"] is True
        return
    result = native_flash.flash_application(arguments, context)
    assert calls == ["write", "run"]
    assert result["application_run"]["boot_id"] == 2


@pytest.mark.parametrize("returncode", [2, 7, 42])
def test_native_exit_code_survives_gateway_failure(tmp_path, monkeypatch, returncode):
    from mosaico_cli import gateway

    context = SimpleNamespace(directory=tmp_path, status=Mock())
    operation = {"operation_id": "native-1", "status": "failed", "error": "IDF failed",
                 "progress": {"native_returncode": returncode}}
    monkeypatch.setattr(gateway, "gateway_json", Mock(side_effect=[
        {"capabilities": ["local-host-operations/v1", "native-flash/v1"]}, {"operation": operation},
    ]))
    with pytest.raises(NativeFlashError) as error:
        gateway.run_host_operation(context, gateway.GatewaySession(
            Path("python"), Path("iris"), ("--url", "http://127.0.0.1:8443"), None, False),
            {"action": "host.flash"}, timeout=1)
    assert error.value.exit_code == returncode


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_native_output_is_complete_even_when_command_finishes_before_poll(
    tmp_path, monkeypatch, capsysbinary, json_output, newline,
):
    from mosaico_cli import gateway

    output = (b"native line" + newline) * 7000
    log = tmp_path / "native.log"
    log.write_bytes(output)
    context = SimpleNamespace(directory=tmp_path, status=Mock(), note=Mock(), json_output=json_output)
    operation = {"operation_id": "native-1", "status": "succeeded",
                 "result": {"returncode": 0, "log_path": str(log)}, "progress": {"log_path": str(log)}}
    monkeypatch.setattr(gateway, "gateway_json", Mock(side_effect=[
        {"capabilities": ["local-host-operations/v1", "native-flash/v1"]}, {"operation": operation},
    ]))
    session = gateway.GatewaySession(Path("python"), Path("iris"), ("--url", "http://127.0.0.1:8443"), None, False)
    assert gateway.run_host_operation(context, session, {"action": "host.flash"}, timeout=1)["returncode"] == 0
    captured = capsysbinary.readouterr()
    assert (captured.err if json_output else captured.out) == output
