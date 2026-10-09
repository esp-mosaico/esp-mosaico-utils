import asyncio
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from iris_gateway.hub import IrisHub
from iris_gateway.protocol import Channel, Frame, MediaType, ProtocolError
from iris_gateway.session import DeviceSession


@pytest.mark.parametrize("path", ["auto", "control", "data"])
def test_snapshot_selects_an_explicit_live_link(path):
    async def scenario():
        data = SimpleNamespace(_console=False, screenshot=AsyncMock(return_value=({}, b"data")))
        control = SimpleNamespace(_console=True, data_session=data,
                                  _require_data_link=lambda: data,
                                  screenshot=AsyncMock(return_value=({}, b"control")))
        hub = IrisHub()
        hub._devices["device"] = control
        description, pixels = await hub.screenshot("device", {"path": path})
        expected = "control" if path == "control" else "data"
        assert pixels == expected.encode()
        assert description["transfer_path"] == expected
        (control if expected == "control" else data).screenshot.assert_awaited_once_with({})
        (data if expected == "control" else control).screenshot.assert_not_called()
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["open", "crc", "stream", "oversize", "cancel"])
def test_invalid_or_cancelled_snapshot_always_closes_its_capture(fault):
    async def scenario():
        session = DeviceSession.__new__(DeviceSession)
        session.info = SimpleNamespace(max_payload=4000)
        payload = session._encode_media_description({"width": 3, "height": 1})
        total = 16 * 1024 * 1024 + 1 if fault == "oversize" else 3
        opened = Frame(channel=Channel.SCREEN, type=MediaType.OPENED, stream_id=41,
                       payload=payload + struct.pack("<I", total))
        if fault == "open":
            opened = Frame(channel=Channel.SCREEN, type=MediaType.OPENED, stream_id=41, payload=b"")
        chunk = Frame(channel=Channel.SCREEN, type=MediaType.DATA,
                      stream_id=42 if fault == "stream" else 41, flags=16,
                      payload=struct.pack("<II", 0, 3) + b"abc" +
                      struct.pack("<I", zlib.crc32(b"abc") ^ (fault == "crc")))

        async def request(channel, type_, *args, **kwargs):
            if type_ == MediaType.OPEN:
                return opened
            assert kwargs["stream_id"] == 41
            if type_ == MediaType.READ:
                if fault == "cancel":
                    raise asyncio.CancelledError()
                return chunk

        session._request = AsyncMock(side_effect=request)
        with pytest.raises(asyncio.CancelledError if fault == "cancel" else ProtocolError):
            await session.screenshot()
        final = session._request.call_args
        assert final.args == (Channel.SCREEN, MediaType.CLOSE)
        assert final.kwargs["stream_id"] == 41
    asyncio.run(scenario())
