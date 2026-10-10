"""One intentional panic on an explicitly selected services coredump fixture.

No flashing, partition changes or coredump erasure. Save any existing valid
dump before the panic, and preserve the resulting binary with full identity.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

import pytest

from iris_gateway.discovery import discover_iris_usb_devices

from .raw import RawIrisSession

pytestmark = [pytest.mark.iris_e2e, pytest.mark.iris_stage(9)]


def test_real_panic_reconnect_and_coredump(request):
    if os.environ.get("ESP_IRIS_TEST_CRASH_FIXTURE") != "1":
        pytest.skip("explicit installed services coredump fixture required")
    mac = request.config.getoption("--iris-chip-mac").lower()
    expected = (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    ports = [p.path for p in discover_iris_usb_devices()
             if p.serial_number.lower() == mac.replace(":", "") and p.link_role == "data"]
    assert len(ports) == 1
    artifacts = request.config._iris_e2e_artifacts

    async def save(raw, report, name):
        data = bytearray()
        while len(data) < report["core_dump_size"]:
            total, chunk = await raw.session.read_core_dump_chunk(len(data))
            assert total == report["core_dump_size"] and chunk
            data.extend(chunk)
        assert len(data) == report["core_dump_size"]
        (artifacts / name).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    async def scenario():
        raw = RawIrisSession(ports[0])
        try:
            before = await raw.open()
            assert before.device_id == expected
            assert before.project_name == "esp_iris_services_s31_test"
            old = await raw.session.crash_report()
            if old["core_dump_valid"]:
                await save(raw, old, "previous-core.bin")
            await raw.session.rpc(0x7ffc, 1)
        finally:
            await raw.close()
        await asyncio.sleep(3)
        deadline = asyncio.get_running_loop().time() + 40
        while True:
            raw = RawIrisSession(ports[0])
            try:
                after = await raw.open()
                assert after.device_id == expected and after.boot_id != before.boot_id
                report = await raw.session.crash_report()
                assert report["previous_boot_crash"]
                assert report["core_dump_present"] and report["core_dump_valid"]
                assert report["decode_eligible"] and report["core_dump_size"] > 0
                assert report["core_dump_elf_sha256"] == before.firmware_sha256
                digest = await save(raw, report, "core.bin")
                (artifacts / "crash-evidence.json").write_text(json.dumps({
                    "before": before.as_dict(), "after": after.as_dict(),
                    "report": report, "core_sha256": digest,
                }, indent=2))
                break
            except (OSError, ConnectionError, TimeoutError):
                if asyncio.get_running_loop().time() > deadline:
                    raise
            finally:
                await raw.close()
            await asyncio.sleep(.5)

    asyncio.run(scenario())
