"""Installed network fixture acceptance; never flashes or provisions Wi-Fi.

ESP_IRIS_TEST_NETWORK_CONFIG points to a private JSON file containing host,
pairing_token and next_pairing_token. Select the expected MAC explicitly.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from iris_gateway.discovery import discover_iris_usb_devices
from iris_gateway.hub import IrisHub
from iris_gateway.protocol import Channel, ProtocolError

from .raw import RawIrisSession

pytestmark = [pytest.mark.iris_e2e, pytest.mark.iris_stage(8)]


def test_tcp_data_first_binding_services_rotation_and_reconnect(request):
    config_path = os.environ.get("ESP_IRIS_TEST_NETWORK_CONFIG")
    if not config_path:
        pytest.skip("private installed-fixture network configuration required")
    config = json.loads(Path(config_path).read_text())
    host = config["host"]
    token, next_token = config["pairing_token"], config["next_pairing_token"]
    mac = request.config.getoption("--iris-chip-mac").lower()
    expected = (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    evidence = {}

    async def failed(candidate, *, owner, data=False):
        raw = RawIrisSession("19773" if data else "19772", tcp_host=host,
                             pairing_token=candidate, owner_id=owner, data_link=data)
        try:
            with pytest.raises((ProtocolError, ConnectionError, TimeoutError, OSError)):
                await asyncio.wait_for(raw.open(), 3)
        finally:
            await raw.close()
            await asyncio.sleep(.2)

    async def scenario():
        # Reset only this fixture's private token selector so acceptance can
        # be repeated after a prior run completed or stopped after rotation.
        ports = [p.path for p in discover_iris_usb_devices()
                 if p.serial_number.lower() == mac.replace(":", "") and p.link_role == "data"]
        assert len(ports) == 1
        setup = RawIrisSession(ports[0])
        try:
            assert (await setup.open()).device_id == expected
            await setup.session.rpc(0x7ffe, 7, b"\x00")
        finally:
            await setup.close()
        await asyncio.sleep(.2)
        owner = os.urandom(16)
        await failed(None, owner=owner, data=True)
        await failed("00" * 32, owner=owner, data=True)
        data = RawIrisSession("19773", tcp_host=host, pairing_token=token,
                              owner_id=owner, data_link=True)
        control = RawIrisSession("19772", tcp_host=host, pairing_token=token,
                                 owner_id=owner, data_link=False)
        try:
            first = await data.open()
            assert first.device_id == expected
            # Same IP and valid token do not bind a different control owner.
            await failed(token, owner=os.urandom(16))
            paired = await control.open()
            assert paired.device_id == first.device_id
            assert paired.boot_id == first.boot_id
            assert paired.session_id != first.session_id
            assert await control.session.rpc(1, 1, b"TCP control") == b"TCP control"
            desc, pixels = await control.session.screenshot({"width": 32, "height": 32})
            assert len(pixels) == 2048
            evidence["data_first"] = {"device_id": first.device_id, "boot_id": first.boot_id,
                "data_session": first.session_id, "control_session": paired.session_id}
        finally:
            await control.close()
            await data.close()
        await asyncio.sleep(.3)

        events = []

        async def event(value):
            events.append(value)

        hub = IrisHub(event_sink=event)

        async def ready(boot=None):
            deadline = asyncio.get_running_loop().time() + 30
            while asyncio.get_running_loop().time() < deadline:
                value = next((item for item in hub.list_devices()
                              if item["device_id"] == expected), None)
                if (value and value["control_link"] and value["data_link"]
                        and (boot is None or value["boot_id"] != boot)):
                    return value
                await asyncio.sleep(.1)
            raise AssertionError(hub.list_endpoints())

        try:
            # Only control address is supplied. Its advertisement discovers
            # data; data authenticates independently before Hub associates it.
            await hub.add_tcp(host, pairing_token=token)
            before = await ready()
            assert before["boot_id"] == first.boot_id
            for path in ("control", "data"):
                desc, pixels = await hub.screenshot(expected, {"width": 32, "height": 32, "path": path})
                assert desc["transfer_path"] == path and len(pixels) == 2048
            payload = bytes(range(256)) * 512

            async def chunks():
                for offset in range(0, len(payload), 777):
                    yield payload[offset:offset + 777]

            name = "tcp-02-roundtrip.bin"
            for volume in ("fs", "atomic"):
                result = await hub.file_upload(expected, volume, name, chunks(), total_size=len(payload))
                assert result["sha256"] == hashlib.sha256(payload).hexdigest()
                received = b"".join([part async for part in hub.file_download(expected, volume, name)])
                assert received == payload
                await hub.file_delete(expected, volume, name)

            for channel in (Channel.IMAGE, Channel.AUDIO):
                queue = hub.subscribe_media(expected, channel)
                try:
                    started = await hub.mirror_start(expected, channel, fps=10)
                    frame = await asyncio.wait_for(queue.get(), 5)
                    assert frame["stream_id"] == started["stream_id"]
                    await hub.mirror_stop(expected, channel)
                finally:
                    hub.unsubscribe_media(expected, channel, queue)
            # A control disconnect preserves the independently bound stream.
            queue = hub.subscribe_media(expected, Channel.IMAGE)
            started = await hub.mirror_start(expected, Channel.IMAGE, fps=10)
            await asyncio.wait_for(queue.get(), 5)
            await hub._remove_endpoint(before["control_link"]["endpoint"])
            while not queue.empty():
                queue.get_nowait()
            assert (await asyncio.wait_for(queue.get(), 5))["stream_id"] == started["stream_id"]
            await hub.add_tcp(host, pairing_token=token)
            repaired = await ready()
            assert repaired["data_link"]["session_id"] == before["data_link"]["session_id"]
            await hub.mirror_stop(expected, Channel.IMAGE)
            hub.unsubscribe_media(expected, Channel.IMAGE, queue)
            evidence["services"] = {"roundtrip_bytes": len(payload), "control_reconnect": repaired}
            await hub.rpc(expected, 0x7ffe, 7, b"\x01")
        finally:
            await hub.close()

        await asyncio.sleep(.3)
        await failed(token, owner=owner)
        rotated = RawIrisSession("19772", tcp_host=host, pairing_token=next_token,
                                  owner_id=owner, data_link=False)
        try:
            info = await rotated.open()
            await rotated.session.restart(250)
        finally:
            await rotated.close()
        await asyncio.sleep(3)
        hub = IrisHub(event_sink=event)
        try:
            await hub.add_tcp(host, pairing_token=next_token)
            final = await ready(info.boot_id)
            await hub.status(expected)
            await asyncio.sleep(.2)
            assert any(event.get("event_name") == "healthy" and
                       str(event.get("boot_id")) == str(final["boot_id"]) for event in events)
            evidence["rotated_after_restart"] = final
        finally:
            await hub.close()
            artifacts = request.config._iris_e2e_artifacts
            (artifacts / "tcp-evidence.json").write_text(json.dumps(evidence, indent=2))
            (artifacts / "tcp-events.json").write_text(json.dumps(events, indent=2))

    asyncio.run(scenario())
