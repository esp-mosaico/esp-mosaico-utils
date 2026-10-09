"""Exercise an installed services fixture without flashing or erasing it.

Requires explicit MAC selection and exclusive access to its Iris endpoints.
Writes only the fixture's disposable file volumes; lifecycle restarts Iris.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from iris_gateway.discovery import discover_iris_usb_devices

from . import test_20_usb_core as core
from . import test_30_services as services
from .raw import RawIrisSession

pytestmark = [pytest.mark.iris_e2e, pytest.mark.iris_stage(7)]


@pytest.mark.parametrize("scenario", [
    core.test_usb_handshake_status_ping_and_invalid_frames,
    core.test_rpc_jobs_log_overflow_and_resource_boundaries,
    services.test_screenshot_and_pointer_are_observed_on_device,
    services.test_image_and_audio_formats_have_deterministic_payloads,
    services.test_fat_read_write_read_only_and_littlefs_atomic_replace,
    services.test_raw_file_errors_abort_and_disconnect_cleanup,
    core.test_lifecycle_reconnect_preserves_identity_and_releases_resources,
], ids=lambda scenario: scenario.__name__.removeprefix("test_"))
def test_installed_fixture_faults(request, scenario):
    mac = request.config.getoption("--iris-chip-mac").lower()
    expected = (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    serial = os.environ.get("ESP_IRIS_TEST_USB_SERIAL", mac.replace(":", ""))
    ports = [port.path for port in discover_iris_usb_devices()
             if port.serial_number.lower() == serial and port.link_role == "data"]
    assert len(ports) == 1, ports

    async def identity():
        raw = RawIrisSession(ports[0])
        try:
            info = await raw.open()
            assert info.device_id == expected
            assert info.project_name.startswith("esp_iris_services_")
        finally:
            await raw.close()

    asyncio.run(identity())
    board = SimpleNamespace(discover_application_port=lambda: ports[0])
    scenario(board, "services_usb")
