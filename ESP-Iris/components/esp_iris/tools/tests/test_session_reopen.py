from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock

import pytest

from iris_gateway.protocol import (
    Capability,
    Channel,
    ControlType,
    Frame,
    ProtocolError,
    TlvTag,
    decode_frame,
    encode_tlv,
)
from iris_gateway.session import DeviceSession


@pytest.mark.parametrize("authenticated", [False, True])
def test_negotiated_reopen_waits_for_fresh_session(authenticated: bool) -> None:
    async def scenario() -> None:
        link = AsyncMock()
        link.endpoint = "fake:usj"
        link.console = False
        session = DeviceSession(link, AsyncMock(), AsyncMock(),
                                pairing_token=b"a" * 32 if authenticated else None)
        session._complete_ready = AsyncMock()
        hello = encode_tlv([
            (TlvTag.DEVICE_ID, b"d" * 16), (TlvTag.BOOT_ID, struct.pack("<Q", 7)),
            (TlvTag.PROTOCOL_VERSION, struct.pack("<H", 2)),
            (TlvTag.LINK_ROLE, b"\x01"),
            (TlvTag.CAPABILITIES, struct.pack("<Q", Capability.SESSION_REOPEN)),
            (TlvTag.AUTH_MODE, bytes([int(authenticated)])),
            (TlvTag.AUTH_CHALLENGE, b"c" * 32),
        ])
        old = Frame(channel=Channel.CONTROL, type=ControlType.HELLO,
                    session_id=20, sequence=1, payload=hello)
        await session._handle_hello(old)
        ack = decode_frame(link.write.call_args.args[0][:-1])
        assert ack.flags == 1 << 5 and ack.session_id == 20
        session._complete_ready.assert_not_called()
        await session._handle_hello(old)  # lost reply: same-session repeat is safe
        session._complete_ready.assert_not_called()
        await session._handle_frame(Frame(channel=Channel.CONTROL,
            type=ControlType.AUTH_RESULT, session_id=20, payload=b"\x01"), 0)
        session._complete_ready.assert_not_called()
        session._last_rx_sequence[0] = 99
        fresh = Frame(channel=Channel.CONTROL, type=ControlType.HELLO,
                      session_id=21, sequence=1, payload=hello)
        await session._handle_hello(fresh)
        ack = decode_frame(link.write.call_args.args[0][:-1])
        assert ack.flags == 0 and ack.session_id == 21 and ack.sequence == 1
        assert session._last_rx_sequence[0] is None
        session._complete_ready.assert_not_called()
        await session._handle_frame(Frame(channel=Channel.CONTROL,
            type=ControlType.AUTH_RESULT, session_id=21, sequence=2,
            payload=b"\x01"), 0)
        session._complete_ready.assert_awaited_once()
        await session._handle_hello(fresh)
        assert decode_frame(link.write.call_args.args[0][:-1]).flags == 0
        with pytest.raises(ProtocolError):
            await session._handle_hello(old)
    asyncio.run(scenario())


@pytest.mark.parametrize("authenticated", [False, True])
def test_release_binding_authenticates_reopen_without_committing_new_session(authenticated):
    async def scenario():
        import hashlib
        import hmac

        from iris_gateway.console_protocol import decode_record

        link = AsyncMock(console=True, endpoint="fake:release-console")
        unready = AsyncMock()
        session = DeviceSession(link, AsyncMock(), AsyncMock(), on_unready=unready,
                                pairing_token=b"a" * 32 if authenticated else None)
        payload = encode_tlv([
            (TlvTag.DEVICE_ID, b"d" * 16), (TlvTag.BOOT_ID, struct.pack("<Q", 7)),
            (TlvTag.PROTOCOL_VERSION, struct.pack("<H", 2)), (TlvTag.LINK_ROLE, b"\0"),
            (TlvTag.CAPABILITIES, struct.pack("<Q", Capability.SESSION_REOPEN)),
            (TlvTag.AUTH_MODE, bytes([int(authenticated)])), (TlvTag.AUTH_CHALLENGE, b"c" * 32),
        ])
        def hello(session_id):
            return Frame(channel=Channel.CONTROL, type=ControlType.HELLO,
                         session_id=session_id, payload=payload)
        await session._handle_hello(hello(20))
        await session._handle_hello(hello(21))
        await session._handle_frame(Frame(channel=Channel.CONTROL, type=ControlType.AUTH_RESULT,
                                         session_id=21, sequence=1, payload=b"\1"), 0)
        capture_id = session.capture_id
        async def reply(wire):
            frame = decode_record(wire, request=True)
            if frame.type != ControlType.HELLO_ACK:
                return
            assert frame.session_id == 21 and frame.flags == 1 << 5
            if authenticated:
                binding, nonce, proof = frame.payload[:17], frame.payload[17:33], frame.payload[33:]
                message = b"ESP-Iris-auth-0.2" + b"d" * 16 + struct.pack("<QI", 7, 21) + b"c" * 32 + nonce + binding
                assert hmac.compare_digest(proof, hmac.new(b"a" * 32, message, hashlib.sha256).digest())
            await session._handle_frame(hello(21), 0)
            assert not session._release_waiter.done()
            await session._handle_frame(hello(22), 0)
        link.write.side_effect = reply
        try:
            await session.release_binding()
            unready.assert_awaited_once_with(session)
            assert not session.console_available and session.info is None
            assert session.capture_only and session.capture_id == capture_id
            assert not session._closed
            sent = [decode_record(call.args[0], request=True) for call in link.write.call_args_list]
            assert not any(frame.session_id == 22 for frame in sent)
        finally:
            await session.close()
    asyncio.run(scenario())
