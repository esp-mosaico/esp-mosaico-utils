from __future__ import annotations

import asyncio
import json
import os
import struct
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from iris_gateway.hub import IrisHub
from iris_gateway.pairing import PairingStore
from iris_gateway.protocol import (
    Capability,
    Channel,
    ControlType,
    Frame,
    TlvTag,
    Transport,
    decode_frame,
    encode_frame,
    encode_tlv,
)
from iris_gateway.session import DeviceSession
from test_single_device_selection import D, gateway

OTHER = "ffeeddccbbaa99887766554433221100"
TOKEN = "ab" * 32


def test_credentials_survive_restart_and_are_private(tmp_path):
    store = PairingStore(tmp_path / "pairings")
    store.remember(D, TOKEN)
    store.remember(OTHER, "cd" * 32)
    reopened = PairingStore(store.root)
    assert reopened.get(D) == TOKEN
    assert reopened.get(OTHER) == "cd" * 32
    assert reopened.devices() == sorted([D, OTHER])
    if os.name != "nt":
        assert store.root.stat().st_mode & 0o777 == 0o700
        assert (store.root / (D + ".json")).stat().st_mode & 0o777 == 0o600
    reopened.forget(D)
    assert store.get(D) is None
    assert store.get(OTHER) == "cd" * 32


@pytest.mark.parametrize("device_id,token", [("../escape", TOKEN), (D, "short"), (D, "gg" * 32)])
def test_invalid_credentials_do_not_create_files(tmp_path, device_id, token):
    store = PairingStore(tmp_path / "pairings")
    with pytest.raises(ValueError):
        store.remember(device_id, token)
    assert not store.root.exists()


def test_corrupted_or_public_credentials_fail_closed(tmp_path):
    store = PairingStore(tmp_path / "pairings")
    store.remember(D, TOKEN)
    path = store.root / (D + ".json")
    if os.name != "nt":
        path.chmod(0o644)
        with pytest.raises(PermissionError):
            store.get(D)
        path.chmod(0o600)
    path.write_text(json.dumps({"device_id": OTHER, "token": TOKEN}))
    with pytest.raises(ValueError, match="identity"):
        store.get(D)


def test_manual_pairing_is_saved_only_after_success(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            g.connect.side_effect = ConnectionError("pairing proof was rejected")
            response = await g.client.post("/v2/project/acquire", json={
                "endpoint": "tcp:192.0.2.1:19772", "pairing_token": TOKEN})
            assert response.status == 400
            assert g.project.service.pairings.devices() == []
            assert g.project.tokens == {}
        async with gateway(tmp_path, "b") as g:
            response = await g.client.post("/v2/project/acquire", json={
                "endpoint": "tcp:192.0.2.1:19772", "pairing_token": TOKEN})
            assert response.status == 200
            assert g.project.service.pairings.get(D) == TOKEN
        async with gateway(tmp_path, "c") as g:
            assert g.hub.pairing_lookup(D) == TOKEN
            assert g.hub.pairing_lookup(OTHER) is None
    asyncio.run(scenario())


def test_paired_network_device_can_be_selected_after_address_change(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            g.project.service.pairings.remember(D, TOKEN)
            endpoint = "tcp:192.0.2.99:19772"
            g.hub._candidates[endpoint] = {"endpoint": endpoint, "present": True, "discovery": "mdns",
                "advertised_device_id": D, "pairing": "hmac", "link_role": "control"}
            response = await g.client.post("/v2/project/acquire", json={"auto": True})
            assert response.status == 200, await response.text()
            assert (await response.json())["device"]["device_id"] == D
            assert g.connect.call_args.args[0] == endpoint
    asyncio.run(scenario())


def test_replacing_token_reauthenticates_and_failure_keeps_saved_key(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            endpoint = "tcp:192.0.2.1:19772"
            response = await g.client.post("/v2/project/acquire", json={"endpoint": endpoint, "pairing_token": TOKEN})
            assert response.status == 200
            g.hub.suspend_owned = AsyncMock(side_effect=lambda device_id: g.live.clear())
            g.connect.side_effect = ConnectionError("pairing proof was rejected")
            response = await g.client.post("/v2/project/acquire", json={
                "device_id": D, "endpoint": endpoint, "pairing_token": "cd" * 32})
            assert response.status == 400
            g.hub.suspend_owned.assert_awaited_once_with(D)
            assert g.project.service.pairings.get(D) == TOKEN
    asyncio.run(scenario())


def test_multiple_paired_network_devices_require_selection(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            for device_id, host in ((D, "192.0.2.1"), (OTHER, "192.0.2.2")):
                g.project.service.pairings.remember(device_id, TOKEN)
                endpoint = f"tcp:{host}:19772"
                g.hub._candidates[endpoint] = {"endpoint": endpoint, "present": True, "discovery": "mdns",
                    "advertised_device_id": device_id, "pairing": "hmac", "link_role": "control"}
            response = await g.client.post("/v2/project/acquire", json={"auto": True})
            assert response.status == 400
            g.connect.assert_not_awaited()
    asyncio.run(scenario())


def test_tcp_admission_waits_for_supervisor_after_transient_reset(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            async def connect(endpoint, metadata, **kwargs):
                g.hub._endpoint_states[endpoint] = {
                    "endpoint": endpoint, "error": "Connection reset by peer",
                    "updated_monotonic_ns": time.monotonic_ns()}
                async def ready():
                    await asyncio.sleep(0.1)
                    g.registry.bind(endpoint, D)
                    g.live.append({"device_id": D, "endpoint": endpoint, "boot_id": 7})
                asyncio.create_task(ready())
            g.connect.side_effect = connect
            response = await g.client.post("/v2/project/acquire", json={
                "endpoint": "tcp:192.0.2.1:19772", "timeout": 1})
            assert response.status == 200, await response.text()
            g.connect.assert_awaited_once()
    asyncio.run(scenario())


def hello(device_id=D, *, transport=Transport.TCP, role=0, auth=1, reopen=False):
    return Frame(channel=Channel.CONTROL, type=ControlType.HELLO, session_id=11, payload=encode_tlv([
        (TlvTag.DEVICE_ID, bytes.fromhex(device_id)), (TlvTag.PROTOCOL_VERSION, struct.pack("<H", 2)),
        (TlvTag.BOOT_ID, struct.pack("<Q", 9)), (TlvTag.LINK_ROLE, bytes([role])),
        (TlvTag.TRANSPORT, bytes([transport])), (TlvTag.AUTH_MODE, bytes([auth])),
        (TlvTag.AUTH_CHALLENGE, b"x" * 32), (TlvTag.CAPABILITIES, struct.pack("<Q",
            Capability.USB_PAIRING | (Capability.SESSION_REOPEN if reopen else 0))),
    ]))


def test_hello_resolves_per_device_credentials_without_using_ip(tmp_path):
    async def scenario():
        store = PairingStore(tmp_path / "pairings")
        for device_id, token in ((D, TOKEN), (OTHER, "cd" * 32)):
            store.remember(device_id, token)
            link = SimpleNamespace(console=True, endpoint="tcp:new-address:19772", write=AsyncMock(), close=AsyncMock())
            session = DeviceSession(link, AsyncMock(), AsyncMock(), pairing_lookup=store.get)
            try:
                await session._handle_hello(hello(device_id))
                assert session._pairing_token == bytes.fromhex(token)
                assert not session._ready.is_set()
            finally:
                await session.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("transport", [Transport.TCP, Transport.UART, Transport.USB_SERIAL_JTAG])
def test_pairing_never_uses_network_or_console_only_transports(transport):
    async def scenario():
        link = SimpleNamespace(console=True, endpoint="fake:control", write=AsyncMock(), close=AsyncMock())
        session = DeviceSession(link, AsyncMock(), AsyncMock())
        try:
            await session._handle_hello(hello(transport=transport, auth=0))
            session._ready.set()
            with pytest.raises(ValueError, match="USB"):
                await session.pairing_token_over_usb()
        finally:
            await session.close()
    asyncio.run(scenario())


def test_usb_pairing_uses_bound_binary_data_without_console_events():
    async def scenario():
        sessions = []
        events = AsyncMock()
        try:
            for role in (0, 1):
                link = SimpleNamespace(console=role == 0, endpoint=f"usb:{role}", write=AsyncMock(), close=AsyncMock())
                session = DeviceSession(link, AsyncMock(), events, owner_id=b"o" * 16)
                await session._handle_hello(hello(transport=Transport.USB, role=role, auth=0))
                session._ready.set()
                sessions.append(session)
            control, data = sessions
            control.data_session = data
            data._request = AsyncMock(return_value=Frame(
                channel=Channel.CONTROL, type=ControlType.PAIRING_RESPONSE, payload=TOKEN.encode()))
            assert await control.pairing_token_over_usb() == TOKEN
            data._request.assert_awaited_once_with(Channel.CONTROL, ControlType.PAIRING_REQUEST)
            events.assert_not_awaited()
        finally:
            for session in sessions:
                await session.close()
    asyncio.run(scenario())


def test_pairing_http_and_audit_never_return_secret(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            response = await g.client.post("/v2/project/acquire", json={"endpoint": "tcp:host:19772"})
            assert response.status == 200
            session = SimpleNamespace(pairing_token_over_usb=AsyncMock(return_value=TOKEN))
            g.hub.get = lambda device_id: session
            response = await g.client.post(f"/v2/devices/{D}/pairing", json={})
            assert response.status == 200, await response.text()
            assert await response.json() == {"device_id": D, "paired": True}
            inventory = await g.client.get("/v2/pairings")
            assert await inventory.json() == {"devices": [D]}
            assert g.project.service.pairings.get(D) == TOKEN
            rows = g.project.service.store.db.execute("SELECT details_json FROM system_audit").fetchall()
            assert TOKEN not in repr([tuple(row) for row in rows])
            response = await g.client.post("/v2/project/release", json={"device_id": D})
            assert response.status == 200
            response = await g.client.delete(f"/v2/pairings/{D}")
            assert response.status == 200
            assert g.project.service.pairings.get(D) is None
    asyncio.run(scenario())


@pytest.mark.parametrize("reopen", [False, True])
def test_authentication_rejection_is_not_hidden_by_closed_link(reopen):
    from test_hub import SupervisorLink

    async def scenario():
        class RejectedLink(SupervisorLink):
            async def write(self, data):
                frame = decode_frame(data[:-1])
                if frame.type == ControlType.HELLO_ACK:
                    await self.incoming.put(encode_frame(Frame(channel=Channel.CONTROL,
                        type=ControlType.ERROR if reopen else ControlType.AUTH_RESULT, flags=2,
                        session_id=frame.session_id,
                        payload=struct.pack("<IBB2x", 0x103, 0, 2) if reopen else b"\x00")))
        async def opener():
            link = RejectedLink(11)
            link.incoming.get_nowait()
            link.incoming.put_nowait(encode_frame(hello(role=1, reopen=reopen)))
            return link
        hub = IrisHub(reconnect_min_seconds=0.1)
        try:
            hub._add_supervisor("fake:supervisor", opener, pairing_token=TOKEN)
            async def rejected():
                while True:
                    error = hub.list_endpoints()[0].get("error") or ""
                    if error:
                        assert "pairing proof was rejected" in error
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(rejected(), 2)
        finally:
            await hub.close()
    asyncio.run(scenario())
