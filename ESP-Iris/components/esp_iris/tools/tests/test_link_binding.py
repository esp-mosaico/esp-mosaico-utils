from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from iris_gateway.console_protocol import decode_record
from iris_gateway.hub import IrisHub
from iris_gateway.protocol import (
    Channel,
    ControlType,
    Frame,
    ProtocolError,
    TlvTag,
    encode_tlv,
)
from iris_gateway.session import DeviceSession


def hello(role=0, boot=9, session=11):
    return Frame(channel=Channel.CONTROL, type=ControlType.HELLO, session_id=session,
                 payload=encode_tlv([
                     (TlvTag.DEVICE_ID, b"d" * 16),
                     (TlvTag.PROTOCOL_VERSION, struct.pack("<H", 2)),
                     (TlvTag.BOOT_ID, struct.pack("<Q", boot)),
                     (TlvTag.LINK_ROLE, bytes([role])),
                 ]))


def test_console_binding_requires_positive_device_confirmation():
    async def scenario():
        link = SimpleNamespace(console=True, endpoint="fake:console", write=AsyncMock(), close=AsyncMock())
        ready = AsyncMock()
        session = DeviceSession(link, ready, AsyncMock(), owner_id=b"o" * 16)
        await session._handle_hello(hello())
        ack = decode_record(link.write.call_args.args[0], request=True)
        assert ack.payload == b"\x00" + b"o" * 16
        assert not session._ready.is_set()
        await session._handle_frame(Frame(channel=Channel.CONTROL, type=ControlType.AUTH_RESULT,
            session_id=11, payload=b"\x01"), 0)
        ready.assert_awaited_once()
        await session.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("role", [1, 7])
def test_console_refuses_wrong_endpoint_role(role):
    async def scenario():
        link = SimpleNamespace(console=True, endpoint="fake:console", write=AsyncMock(), close=AsyncMock())
        session = DeviceSession(link, AsyncMock(), AsyncMock())
        with pytest.raises(ProtocolError, match="role"):
            await session._handle_hello(hello(role=role))
        link.write.assert_not_called()
    asyncio.run(scenario())


@pytest.mark.parametrize("mismatch", ["boot", "owner"])
def test_hub_refuses_false_control_data_association(mismatch):
    async def scenario():
        hub = IrisHub()
        async def discard(value): pass
        data = DeviceSession(SimpleNamespace(console=False, endpoint="fake:data", close=AsyncMock()),
                             discard, discard, owner_id=b"a" * 16)
        control = DeviceSession(SimpleNamespace(console=True, endpoint="fake:control", close=AsyncMock()),
                                discard, discard, owner_id=b"b" * 16 if mismatch == "owner" else b"a" * 16)
        for session, role, boot in ((data, 1, 9), (control, 0, 10 if mismatch == "boot" else 9)):
            session.link.write = AsyncMock()
            await session._handle_hello(hello(role=role, boot=boot))
            hub._endpoint_states[session.link.endpoint] = {"attempt": 1}
        await hub._on_ready(data)
        with pytest.raises(ProtocolError, match="binding"):
            await hub._on_ready(control)
        assert hub._devices[data.info.device_id] is data
        assert hub._links[data.info.device_id] == {"data": data}
    asyncio.run(scenario())


def test_data_first_binding_and_control_disconnect_preserve_data():
    async def scenario():
        hub = IrisHub()
        sessions = []
        for role in (1, 0):
            link = SimpleNamespace(console=role == 0, endpoint=f"fake:{role}",
                                   write=AsyncMock(), close=AsyncMock())
            session = DeviceSession(link, AsyncMock(), AsyncMock(), owner_id=b"a" * 16)
            await session._handle_hello(hello(role=role, session=11+role))
            hub._endpoint_states[link.endpoint] = {"attempt": 1}
            await hub._on_ready(session)
            sessions.append(session)
        data, control = sessions
        assert control.data_session is data
        await hub._drop_session(control)
        assert hub._devices[data.info.device_id] is data
        data.link.close.assert_not_called()
    asyncio.run(scenario())
