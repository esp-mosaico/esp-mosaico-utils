"""0.2 dual-CDC acceptance for an already installed services fixture.

Never flashes. Select the board explicitly with --iris-chip-mac and release
other endpoint owners before running. Only fixture file volumes are modified.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid

import pytest

from iris_gateway.discovery import discover_iris_usb_devices
from iris_gateway.hub import IrisHub
from iris_gateway.media import encode_media_image
from iris_gateway.protocol import Channel, MediaType

from .contracts import MEDIA_CONFIGURE_V1

pytestmark = [pytest.mark.iris_e2e, pytest.mark.iris_stage(6)]


def test_independent_usb_data_control_and_services(request):
    mac = request.config.getoption("--iris-chip-mac").lower()
    expected = (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    artifacts = request.config._iris_e2e_artifacts
    serial = os.environ.get("ESP_IRIS_TEST_USB_SERIAL", mac.replace(":", ""))
    ports = {port.link_role: port for port in discover_iris_usb_devices()
             if port.serial_number.lower() == serial}
    assert set(ports) == {"control", "data"}, ports
    assert ports["control"].interface == "ESP-Iris 0.2 console"
    assert ports["data"].interface == "ESP-Iris 0.2 data"

    async def scenario():
        events = []
        evidence = {}

        async def event(value):
            events.append(value)

        hub = IrisHub(event_sink=event)

        async def links(control, data):
            deadline = asyncio.get_running_loop().time() + 15
            while asyncio.get_running_loop().time() < deadline:
                current = next((item for item in hub.list_devices()
                                if item["device_id"] == expected), None)
                if current and bool(current["control_link"]) == control and bool(current["data_link"]) == data:
                    assert current["hardware_mac"] == mac
                    return current
                await asyncio.sleep(.05)
            raise AssertionError(hub.list_endpoints())

        async def chunks(payload):
            for offset in range(0, len(payload), 777):
                yield payload[offset:offset + 777]

        async def read(volume, name):
            return b"".join([part async for part in hub.file_download(expected, volume, name)])

        try:
            await hub.add_usb(ports["data"].path)
            first = await links(False, True)
            evidence["data_first"] = first
            data_endpoint = first["data_link"]["endpoint"]
            boot = first["boot_id"]
            assert (await hub.status(expected))["boot_id"] == boot
            await hub.add_usb(ports["control"].path)
            paired = await links(True, True)
            evidence["paired"] = paired
            control_endpoint = paired["control_link"]["endpoint"]
            assert paired["boot_id"] == boot
            assert paired["control_link"]["session_id"] != paired["data_link"]["session_id"]
            assert await hub.rpc(expected, 1, 1, b"dual control") == b"dual control"

            for path in ("auto", "control", "data"):
                desc, pixels = await hub.screenshot(expected, {"width": 32, "height": 32, "path": path})
                assert desc["transfer_path"] == ("control" if path == "control" else "data")
                assert len(pixels) == 2048
                image = encode_media_image(desc, pixels)
                (artifacts / f"dual-{path}.png").write_bytes(image.data)

            for channel, format_, expected_bytes in (
                (Channel.IMAGE, 1, 128), (Channel.IMAGE, 2, 192),
                (Channel.IMAGE, 3, None), (Channel.IMAGE, 4, None),
                (Channel.AUDIO, 0x100, 32), (Channel.AUDIO, 0x101, 3),
            ):
                queue = hub.subscribe_media(expected, channel)
                try:
                    await hub.rpc(expected, 0x7ffe, 4, MEDIA_CONFIGURE_V1.pack(channel, format_, 10))
                    state = await hub.mirror_start(expected, channel, fps=30)
                    received = await asyncio.wait_for(queue.get(), 5)
                    assert received["stream_id"] == state["stream_id"]
                    assert received["description"]["format"] == format_
                    if expected_bytes is not None:
                        assert len(received["data"]) == expected_bytes
                    elif format_ == 3:
                        assert received["data"].startswith(b"\xff\xd8")
                    else:
                        assert received["data"].startswith(b"\x89PNG\r\n\x1a\n")
                    await hub.mirror_stop(expected, channel)
                finally:
                    hub.unsubscribe_media(expected, channel, queue)

            volumes = await hub.file_volumes(expected)
            assert {item["id"] for item in volumes["volumes"]} == {"fs", "ro", "atomic"}
            payload = bytes(range(256)) * 512
            name = f"e2e-{uuid.uuid4().hex}.bin"
            for volume in ("fs", "atomic"):
                uploaded = await hub.file_upload(expected, volume, name, chunks(payload), total_size=len(payload))
                assert uploaded["sha256"] == hashlib.sha256(payload).hexdigest()
                assert await read(volume, name) == payload
                await hub.file_delete(expected, volume, name)
            evidence["file_roundtrip_bytes"] = len(payload)

            queue = hub.subscribe_media(expected, Channel.IMAGE)
            await hub.rpc(expected, 0x7ffe, 4, MEDIA_CONFIGURE_V1.pack(Channel.IMAGE, 1, 10))
            stream = await hub.mirror_start(expected, Channel.IMAGE, fps=30)
            await asyncio.wait_for(queue.get(), 5)
            await hub._remove_endpoint(control_endpoint)
            data_only = await links(False, True)
            assert data_only["boot_id"] == boot
            assert data_only["data_link"]["session_id"] == paired["data_link"]["session_id"]
            while not queue.empty():
                queue.get_nowait()
            assert (await asyncio.wait_for(queue.get(), 5))["stream_id"] == stream["stream_id"]
            assert b"fixture" in await read("fs", "README.txt")
            await hub.add_usb(ports["control"].path)
            repaired = await links(True, True)
            assert repaired["boot_id"] == boot
            data = hub.get(expected).data_session
            with pytest.raises(RuntimeError):
                await data._request(Channel.IMAGE, MediaType.MIRROR_STOP, stream_id=stream["stream_id"] + 1)
            await hub.mirror_stop(expected, Channel.IMAGE)
            hub.unsubscribe_media(expected, Channel.IMAGE, queue)

            await hub._remove_endpoint(data_endpoint)
            control_only = await links(True, False)
            assert control_only["boot_id"] == boot
            assert control_only["control_link"]["session_id"] == repaired["control_link"]["session_id"]
            desc, pixels = await hub.screenshot(expected, {"width": 32, "height": 32})
            assert desc["transfer_path"] == "control" and len(pixels) == 2048
            assert await hub.rpc(expected, 1, 1, b"data removed") == b"data removed"
            with pytest.raises(RuntimeError, match="data"):
                await hub.file_volumes(expected)
            await hub.add_usb(ports["data"].path)
            final = await links(True, True)
            assert final["boot_id"] == boot
            assert final["data_link"]["session_id"] != paired["data_link"]["session_id"]
            evidence["final"] = final
        finally:
            evidence["endpoints"] = hub.list_endpoints()
            (artifacts / "dual-evidence.json").write_text(json.dumps(evidence, indent=2))
            (artifacts / "dual-events.json").write_text(json.dumps(events, indent=2))
            await hub.close()

    asyncio.run(scenario())
