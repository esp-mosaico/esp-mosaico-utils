"""A serial reader can survive a dead Iris binding and a transport change."""
from __future__ import annotations

import asyncio
import base64
import struct
from unittest.mock import patch

import pytest
from test_console_capture import ConsoleLink

from iris_gateway.console_protocol import HELLO_COMMAND, decode_record, encode_record
from iris_gateway.hub import IrisHub
from iris_gateway.protocol import Channel, ControlType, Frame, TlvTag, encode_tlv
from iris_gateway.session import DeviceSession

DEVICE = '00112233445566778899aabbccddeeff'

class ControlledConsole(ConsoleLink):
    def __init__(self, endpoint, boot, transport):
        super().__init__()
        self.endpoint, self.boot, self.transport = endpoint, boot, transport
        self.responding = True
        self.sequence = 0
        self.unanswered_clock_requests = 0

    async def send(self, kind, payload, *, request_id=0, flags=0):
        self.sequence += 1
        await self.incoming.put(encode_record(Frame(
            channel=Channel.CONTROL, type=kind, session_id=41,
            sequence=self.sequence, request_id=request_id, flags=flags,
            payload=payload), request=False))

    async def write(self, data):
        self.writes.append(data)
        if data == HELLO_COMMAND:
            if self.responding:
                await self.send(ControlType.HELLO, encode_tlv([
                    (TlvTag.DEVICE_ID, bytes.fromhex(DEVICE)),
                    (TlvTag.BOOT_ID, struct.pack('<Q', self.boot)),
                    (TlvTag.PROTOCOL_VERSION, struct.pack('<H', 2)),
                    (TlvTag.LINK_ROLE, b'\0'),
                    (TlvTag.TRANSPORT, bytes([self.transport])),
                ]))
        elif data.startswith(b'iris @'):
            frame = decode_record(data, request=True)
            if not self.responding:
                if frame.type == ControlType.TIME_SYNC_REQUEST:
                    self.unanswered_clock_requests += 1
                return
            if frame.type == ControlType.HELLO_ACK:
                await self.send(ControlType.AUTH_RESULT, b'\1')
            elif frame.type == ControlType.TIME_SYNC_REQUEST:
                await self.send(ControlType.TIME_SYNC_RESPONSE,
                    frame.payload + struct.pack('<QQ', 1, 2),
                    request_id=frame.request_id, flags=1)

async def until(predicate):
    deadline = asyncio.get_running_loop().time() + 2
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError('Expected state did not occur')
        await asyncio.sleep(0.002)

def fast_session(*args, **kwargs):
    return DeviceSession(*args, clock_sync_interval=0.01,
                         clock_sync_timeout=0.01, **kwargs)


@pytest.mark.parametrize("retire_by_new_boot", [False, True])
def test_silent_control_releases_binding_keeps_raw_capture_and_admits_new_boot(retire_by_new_boot):
    async def scenario():
        events = []
        old = ControlledConsole("fake:stale-usj", 100, 3)
        new = ControlledConsole("fake:live-usb-hs", 101, 1)

        async def sink(event):
            events.append(event)

        async def old_opener():
            return old

        async def new_opener():
            return new

        hub = IrisHub(event_sink=sink, hello_timeout_seconds=0.2)
        factory = DeviceSession if retire_by_new_boot else fast_session
        with patch("iris_gateway.hub.DeviceSession", side_effect=factory), patch.object(
                DeviceSession, "CONSOLE_PROBE_INTERVAL_SECONDS", 0.01):
            try:
                hub._add_supervisor(old.endpoint, old_opener)
                await until(lambda: bool(hub.list_devices()))
                previous = hub.get(DEVICE)
                capture_id = previous.capture_id
                old.responding = False
                if not retire_by_new_boot:
                    await until(lambda: not hub.list_devices())
                    assert old.unanswered_clock_requests >= 2
                    assert not previous.console_available
                else:
                    # An in-flight mutation must fail, never run on the new boot.
                    pending = asyncio.create_task(previous._request(Channel.CONTROL, ControlType.RESTART, timeout=2))
                    await until(lambda: previous._request_lock.locked())
                    queued = asyncio.create_task(previous._request(Channel.CONTROL, ControlType.RESTART, timeout=2))
                    await asyncio.sleep(0)
                hub._add_supervisor(new.endpoint, new_opener)
                await until(lambda: any(d["boot_id"] == 101 for d in hub.list_devices()))
                if retire_by_new_boot:
                    with pytest.raises(ConnectionError):
                        await pending
                    with pytest.raises(ConnectionError):
                        await queued
                    assert previous.capture_only
                    writes = len(old.writes)
                    old.responding = True
                    await asyncio.sleep(0.03)
                    assert len(old.writes) == writes
                raw = b"boot log after Iris retired\r\n"
                await old.incoming.put(raw)
                await until(lambda: any(e.get("data_base64") == base64.b64encode(raw).decode() for e in events))
                assert previous.capture_id == capture_id and not old.closed
                assert not any(e["kind"] == "console_gap" for e in events)
                assert hub.list_devices()[0]["endpoint"] == new.endpoint
                assert new.closed is False
            finally:
                await hub.close()
    asyncio.run(scenario())


def test_live_same_boot_control_is_not_displaced():
    async def scenario():
        first = ControlledConsole("fake:live-usj", 100, 3)
        second = ControlledConsole("fake:other-control", 100, 1)
        async def open_first():
            return first
        async def open_second():
            return second
        hub = IrisHub(hello_timeout_seconds=0.2)
        try:
            hub._add_supervisor(first.endpoint, open_first)
            await until(lambda: bool(hub.list_devices()))
            hub._add_supervisor(second.endpoint, open_second)
            await until(lambda: second.closed)
            assert hub.list_devices()[0]["endpoint"] == first.endpoint
            assert not first.closed
        finally:
            await hub.close()
    asyncio.run(scenario())


def test_console_probe_timeouts_do_not_abort_active_request_and_reauthenticates_after_idle():
    async def scenario():
        link = ControlledConsole("fake:busy-usj", 100, 3)
        async def opener():
            return link
        hub = IrisHub(hello_timeout_seconds=0.2)
        with patch("iris_gateway.hub.DeviceSession", side_effect=fast_session), patch.object(
                DeviceSession, "CONSOLE_PROBE_INTERVAL_SECONDS", 0.01):
            try:
                hub._add_supervisor(link.endpoint, opener)
                await until(lambda: bool(hub.list_devices()))
                session = hub.get(DEVICE)
                capture = session.capture_id
                link.responding = False
                await session._request_lock.acquire()
                await until(lambda: link.unanswered_clock_requests >= 3)
                assert session.console_available and hub.list_devices()
                session._request_lock.release()
                await until(lambda: not hub.list_devices())
                link.responding = True
                await until(lambda: bool(hub.list_devices()))
                assert hub.get(DEVICE) is session
                assert session.capture_id == capture and not link.closed
            finally:
                await hub.close()
    asyncio.run(scenario())
