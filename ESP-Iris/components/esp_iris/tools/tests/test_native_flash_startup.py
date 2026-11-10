from __future__ import annotations

import asyncio
import queue
from unittest.mock import AsyncMock, patch

import pytest
from test_console_capture import ConsoleLink

from iris_gateway.console_protocol import encode_record
from iris_gateway.hub import IrisHub
from iris_gateway.link import SerialLink
from iris_gateway.protocol import Channel, ControlType, Frame
from iris_gateway.session import DeviceSession


class BootPort:
    """Emit the first boot bytes on reset release, not on a later poll."""

    is_open = True
    in_waiting = 0
    dtr = False

    def __init__(self):
        self.incoming = queue.Queue()
        self.writes = []
        self.resets = 0
        self._rts = False

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        if self._rts and not value:
            self.resets += 1
            self.incoming.put(b"ESP-ROM startup\r\nI (1) boot: loaded\r\nheartbeat=0\r\n")
        self._rts = value

    def read(self, size):
        try:
            return self.incoming.get(timeout=0.02)
        except queue.Empty:
            return b""

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def cancel_read(self):
        self.incoming.put(b"")

    def close(self):
        self.is_open = False


async def until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition did not become true")


@pytest.mark.parametrize("reset_fails", [False, True])
def test_post_flash_reader_precedes_single_reset_and_reconnect_never_repeats_it(reset_fails):
    async def scenario():
        events, links, attempts = [], [], []

        async def sink(event):
            events.append(event)

        hub = IrisHub(event_sink=sink, hello_timeout_seconds=0.02,
                      reconnect_min_seconds=0.001, reconnect_max_seconds=0.002)
        endpoint = "usb:location=startup-test"
        metadata = {"vid": 0x10c4, "pid": 0xea60, "endpoint": endpoint,
                    "location": "startup-test", "usb_selection": "explicit"}

        async def opener():
            port = BootPort()
            link = SerialLink("fake", port, endpoint=endpoint)
            original_reset = link.hardware_reset

            async def reset(*args, **kwargs):
                await link.reader_started.wait()
                assert not port.writes  # HELLO must wait until reset completes.
                assert not link._closing and port.is_open
                attempts.append(link)
                if reset_fails:
                    raise OSError("reset circuit unavailable")
                await original_reset(*args, **kwargs)

            link.hardware_reset = reset
            links.append(link)
            return link

        hub._endpoint_states[endpoint] = metadata.copy()
        hub._endpoint_configs[endpoint] = (opener, None)
        hub._host_endpoints.add(endpoint)
        try:
            with patch("iris_gateway.hub.resolve_usb_port", return_value=metadata):
                if reset_fails:
                    with pytest.raises(OSError, match="reset circuit"):
                        await hub.resume_after_host(endpoint, connect=True, reset=True)
                else:
                    result = await hub.resume_after_host(endpoint, connect=True, reset=True)
                    assert result["reader_started_before_reset"]
                    await until(lambda: "heartbeat=0" in "".join(e.get("text", "") for e in events))
                    assert links[0]._serial.resets == 1
                await until(lambda: links[0]._serial.writes)
                assert len(links) == 1
                await links[0].close()
                await until(lambda: len(links) == 2 and links[1]._serial.writes)
                assert len(attempts) == 1
                assert links[1]._serial.resets == 0
                await hub.resume_after_host(endpoint)  # Host-operation cleanup.
                assert len(attempts) == 1
        finally:
            await hub.close()

    asyncio.run(scenario())


def test_cancelled_startup_request_does_not_reset_a_late_connection():
    async def scenario():
        hub = IrisHub(hello_timeout_seconds=0.02)
        endpoint = "usb:location=cancelled-startup"
        port = BootPort()
        link = SerialLink("fake", port, endpoint=endpoint)
        open_gate = asyncio.Event()

        async def opener():
            await open_gate.wait()
            return link

        request = asyncio.get_running_loop().create_future()
        hub._add_supervisor(endpoint, opener, defer_lock=True, startup_reset=request)
        try:
            request.cancel()
            open_gate.set()
            await until(lambda: port.writes)
            assert port.resets == 0
        finally:
            await hub.close()

    asyncio.run(scenario())


def test_pending_reset_captures_text_but_does_not_bind_first_boot_or_send_hello():
    async def scenario():
        link = ConsoleLink()
        sink = AsyncMock()
        session = DeviceSession(link, AsyncMock(), sink)
        session._handle_frame = AsyncMock()
        start = asyncio.Event()
        task = asyncio.create_task(session.run(console_start=start))
        hello = encode_record(Frame(channel=Channel.CONTROL, type=ControlType.HELLO,
                                    session_id=41, payload=b"first boot"), request=False)
        try:
            await link.incoming.put(hello + b"early raw log\r\n")
            await until(lambda: any(call.args[0].get("kind") == "log" for call in sink.call_args_list))
            assert not link.writes
            session._handle_frame.assert_not_called()
            start.set()
            await link.incoming.put(hello)
            await until(lambda: session._handle_frame.call_count == 1 and link.writes)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
