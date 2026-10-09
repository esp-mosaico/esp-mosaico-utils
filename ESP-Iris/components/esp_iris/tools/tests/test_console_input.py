from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from iris_gateway.console_input import encode_console_line
from iris_gateway.console_protocol import decode_record
from iris_gateway.hub import IrisHub
from iris_gateway.protocol import Channel, ControlType
from iris_gateway.session import DeviceSession
from iris_gateway.state_machine import SessionState


@pytest.mark.parametrize("line", ["", " ", "x\ny", "x\ry", "x\x00y", "x\x1by", "x\x7fy", "字" * 86,
                                 "x" * 256, "iris @AAAA", "iris hello", " iris   @AAAA"])
def test_console_rejects_control_bytes_and_machine_records(line):
    with pytest.raises(ValueError):
        encode_console_line(line)


def test_console_preserves_text_and_counts_utf8_bytes():
    assert encode_console_line('set "值 "  ') == 'set "值 "  \n'.encode()
    assert len(encode_console_line("字" * 85)) == 256


def ready_session(link):
    session = DeviceSession(link, AsyncMock(), AsyncMock())
    session.info = SimpleNamespace(session_id=41)
    session.state = SessionState.READY
    session._ready.set()
    return session


def test_text_and_rpc_records_share_one_writer_and_only_control_accepts_text():
    async def scenario():
        wires = []
        writers = 0
        peak = 0
        async def write(wire):
            nonlocal writers, peak
            writers += 1
            peak = max(peak, writers)
            await asyncio.sleep(0.005)
            wires.append(wire)
            writers -= 1
        control = ready_session(SimpleNamespace(console=True, endpoint="usb:control", write=write, close=AsyncMock()))
        data_link = SimpleNamespace(console=False, endpoint="usb:data", write=AsyncMock(), close=AsyncMock())
        data = ready_session(data_link)
        hub = IrisHub()
        hub._links["device"] = {"control": control, "data": data}
        hub._devices["device"] = data  # Text must not follow the generic/data selection.
        result, _ = await asyncio.gather(hub.console_write("device", "iris status"),
                                        control._send(Channel.CONTROL, ControlType.CREDIT, b"123"))
        assert peak == 1
        assert b"iris status\n" in wires
        record = next(wire for wire in wires if wire.startswith(b"iris @"))
        assert decode_record(record, request=True).payload == b"123"
        assert result == {"sent": True, "bytes_written": 12, "endpoint": "usb:control", "completion": "unconfirmed"}
        data_link.write.assert_not_called()
        hub._links["device"].pop("control")
        with pytest.raises(ConnectionError, match="control link"):
            await hub.console_write("device", "help")
        with pytest.raises(ConnectionError, match="control link"):
            await data.console_write("help")
    asyncio.run(scenario())


def test_disconnect_while_waiting_for_writer_never_sends_on_stale_session():
    async def scenario():
        link = SimpleNamespace(console=True, endpoint="usb:control", write=AsyncMock(), close=AsyncMock())
        session = ready_session(link)
        await session._write_lock.acquire()
        pending = asyncio.create_task(session.console_write("help"))
        await asyncio.sleep(0)
        await session.close()
        session._write_lock.release()
        with pytest.raises(ConnectionError):
            await pending
        link.write.assert_not_called()
    asyncio.run(scenario())


def test_partial_write_failure_closes_link_without_retry():
    async def scenario():
        link = SimpleNamespace(console=True, endpoint="usb:control", write=AsyncMock(side_effect=OSError("partial write")), close=AsyncMock())
        session = ready_session(link)
        with pytest.raises(OSError, match="partial write"):
            await session.console_write("set value")
        assert link.write.await_count == 1
        link.close.assert_awaited_once()
        assert not session.console_available
    asyncio.run(scenario())
