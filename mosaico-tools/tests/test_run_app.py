from __future__ import annotations

import base64
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mosaico_cli import run_app
from mosaico_cli.cli import build_parser
from mosaico_cli.errors import (
    DeviceError,
    OperationError,
    OutcomeUnknownError,
    SelectionError,
)


@pytest.fixture
def launch(monkeypatch):
    arguments = build_parser().parse_args([
        "iris", "run-app", "--endpoint", "/dev/ttyUSB0", "--baudrate", "115200", "--timeout", "2",
    ])
    context = SimpleNamespace(log_path=Path("run.log"), status=Mock())
    recovery = {"device_id": "device", "boot_id": 1, "stale": False, "firmware_mode": "recovery",
                "product_contract": "esp-mosaico/v2", "firmware_sha256": "01" * 32}
    application = {**recovery, "boot_id": 2, "firmware_mode": "normal", "firmware_sha256": "a5" * 32}
    payload = struct.pack("<I", 0x210000) + bytes.fromhex(application["firmware_sha256"])
    rpc = Mock(return_value={"payload_base64": base64.b64encode(payload).decode()})
    live = Mock(side_effect=[recovery, DeviceError("rebooting"), application])
    gateway = Mock(return_value=object())
    monkeypatch.setattr(run_app, "ensure_gateway", gateway)
    monkeypatch.setattr(run_app, "connected_devices", Mock(return_value=[recovery]))
    monkeypatch.setattr(run_app, "_live_status", live)
    monkeypatch.setattr(run_app, "gateway_json", rpc)
    now = [0.0]
    monkeypatch.setattr(run_app.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(run_app.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return SimpleNamespace(arguments=arguments, context=context, recovery=recovery,
                           application=application, rpc=rpc, live=live, gateway=gateway)


def test_uart_application_retry_verifies_new_boot_and_image(launch):
    result = run_app.run_application(launch.arguments, launch.context)
    assert result["status"] == "succeeded"
    assert result["previous_boot_id"] == 1 and result["boot_id"] == 2
    assert result["application_address"] == 0x210000
    assert launch.rpc.call_count == 1
    assert launch.rpc.call_args.args[2:] == ("rpc-raw", "device", "0x1202", "8", "--deadline-ms", "10000")
    assert launch.arguments.endpoint == "/dev/ttyUSB0" and launch.arguments.baudrate == 115200


@pytest.mark.parametrize("change", [{"firmware_mode": "normal"}, {"product_contract": "other"}])
def test_retry_rejects_other_firmware_before_mutation(launch, change):
    launch.live.side_effect = [{**launch.recovery, **change}]
    with pytest.raises(DeviceError):
        run_app.run_application(launch.arguments, launch.context)
    launch.rpc.assert_not_called()


def test_flash_run_does_not_restart_an_already_running_application(launch):
    launch.live.side_effect = [launch.application]
    result = run_app.run_application(launch.arguments, launch.context, allow_running=True)
    assert result["status"] == "already_running"
    launch.rpc.assert_not_called()


@pytest.mark.parametrize("reply", [DeviceError("disconnected"), {}, {"payload_base64": "AA=="},
                                   {"payload_base64": base64.b64encode(bytes(36)).decode()}])
def test_unknown_acknowledgement_never_replays(launch, reply):
    if isinstance(reply, Exception):
        launch.rpc.side_effect = reply
    else:
        launch.rpc.return_value = reply
    with pytest.raises(OutcomeUnknownError):
        run_app.run_application(launch.arguments, launch.context)
    assert launch.rpc.call_count == 1


@pytest.mark.parametrize("change", [{"firmware_mode": "recovery"}, {"firmware_sha256": "ff" * 32}])
def test_wrong_image_or_recovery_after_restart_fails_without_retry(launch, change):
    launch.live.side_effect = [launch.recovery, {**launch.application, **change}]
    with pytest.raises(OperationError):
        run_app.run_application(launch.arguments, launch.context)
    assert launch.rpc.call_count == 1


@pytest.mark.parametrize("state", ["old_boot", "disconnected"])
def test_timeout_is_not_reported_as_a_successful_launch(launch, state):
    launch.live.side_effect = None
    launch.live.return_value = launch.recovery
    if state == "disconnected":
        def status(*args):
            if launch.live.call_count == 1:
                return launch.recovery
            raise DeviceError("disconnected")
        launch.live.side_effect = status
    with pytest.raises(OutcomeUnknownError, match="did not reconnect"):
        run_app.run_application(launch.arguments, launch.context)
    assert launch.rpc.call_count == 1


def test_external_profile_cannot_silently_ignore_endpoint(launch):
    launch.arguments.gateway_profile = "remote"
    with pytest.raises(SelectionError):
        run_app.run_application(launch.arguments, launch.context)
    launch.gateway.assert_not_called()
