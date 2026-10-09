"""0.2 acceptance against an already installed service fixture and Gateway.

Explicit --iris-e2e, --iris-chip-mac and ESP_IRIS_TEST_URL are required. These
tests do not flash; the final test resets the identified device in place.
"""
import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
import uuid

import pytest

pytestmark = [pytest.mark.iris_e2e, pytest.mark.iris_stage(5)]


@pytest.fixture(scope="module")
def console_api(request):
    base = os.environ["ESP_IRIS_TEST_URL"].rstrip("/")
    mac = request.config.getoption("--iris-chip-mac").lower()
    expected = (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    artifacts = request.config._iris_e2e_artifacts

    def call(path, body=None, *, method=None, raw=False):
        req = urllib.request.Request(base + "/v2/" + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Operation-ID": str(uuid.uuid4())},
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read()
                return (dict(response.headers), data) if raw else json.loads(data)
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{error.code}: {error.read().decode()}") from error

    def live():
        device = next(item for item in call("devices")["devices"] if item["device_id"] == expected)
        assert device["connected"] and device["hardware_mac"] == mac
        assert device["control_link"] and not device["data_available"]
        return device

    first = live()
    (artifacts / "control-initial.json").write_text(json.dumps(first, indent=2))
    return call, live, expected, artifacts


def test_01_control_rpc_and_snapshot_without_data(console_api):
    call, live, device, artifacts = console_api
    for size in (0, 256, 1024):
        payload = bytes(index % 256 for index in range(size))
        result = call(f"devices/{device}/rpc/raw", {
            "service_id": 1, "method_id": 1, "payload_base64": base64.b64encode(payload).decode()})
        assert base64.b64decode(result["payload_base64"]) == payload
        assert result["operation"]["status"] == "succeeded"
    for path in ("auto", "control"):
        headers, image = call(f"devices/{device}/screenshot?save=true", {"path": path, "width": 32, "height": 32}, raw=True)
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack_from(">II", image, 16) == (32, 32)
        assert json.loads(headers["X-ESP-Iris-Media"])["transfer_path"] == "control"
        (artifacts / f"control-{path}.png").write_bytes(image)
    assert not live()["data_available"]


def test_02_control_jobs_and_log_burst(console_api):
    call, live, device, artifacts = console_api
    result = call(f"devices/{device}/rpc/raw", {"service_id": 1, "method_id": 2})
    job_id = struct.unpack("<I", base64.b64decode(result["payload_base64"]))[0]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = call(f"devices/{device}/jobs/{job_id}")["job"]
        if job["job_state"] == "succeeded":
            break
        time.sleep(.1)
    assert job["job_state"] == "succeeded"
    burst = struct.pack("<HHHH", 20, 20, 128, 0)
    call(f"devices/{device}/rpc/raw", {"service_id": 0x7ffe, "method_id": 2,
                                      "payload_base64": base64.b64encode(burst).decode()})
    # A partial text line must not swallow the following framed response.
    result = call(f"devices/{device}/rpc/raw", {"service_id": 1, "method_id": 1,
                                               "payload_text": "after-log-burst"})
    assert base64.b64decode(result["payload_base64"]) == b"after-log-burst"
    history = call(f"events?device_id={device}")
    (artifacts / "control-log-events.json").write_text(json.dumps(history, indent=2))
    assert any(item.get("kind") == "console_raw" for item in history["events"])
    assert live()["connected"]


def test_03_hardware_reset_captures_boot_and_reconnects(console_api):
    call, live, _device, artifacts = console_api
    before = live()
    result = call("consoles/reset", {"endpoint": before["endpoint"], "mode": "run"})
    assert result["reset"]["reader_started_before_reset"]
    deadline = time.monotonic() + 20
    after = before
    while time.monotonic() < deadline:
        try:
            after = live()
            if after["boot_id"] != before["boot_id"]:
                break
        except (AssertionError, StopIteration):
            pass
        time.sleep(.2)
    assert after["boot_id"] != before["boot_id"]
    assert after["device_id"] == before["device_id"]
    history = call(f"events?endpoint={before['endpoint']}")
    raw = b"".join(base64.b64decode(item["data_base64"]) for item in history["events"]
                   if item.get("kind") == "console_raw")
    assert b"ESP-ROM" in raw and b"2nd stage bootloader" in raw
    (artifacts / "controlled-reset.raw").write_bytes(raw)
    (artifacts / "controlled-reset.json").write_text(json.dumps({"before": before, "after": after,
                                                               "operation": result}, indent=2))
