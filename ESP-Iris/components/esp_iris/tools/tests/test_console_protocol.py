from __future__ import annotations

import base64
import ctypes
import json
import pathlib
import random

import pytest
from test_codec_c_compat import CDecodedFrame, CWireHeader, c_codec  # noqa: F401

from iris_gateway.console_protocol import (
    MAX_RECORD,
    REQUEST_PREFIX,
    RESPONSE_PREFIX,
    ConsoleDecoder,
    decode_record,
    encode_record,
)
from iris_gateway.protocol import MAX_PAYLOAD, Frame, ProtocolError


@pytest.fixture(scope="module")
def console_codec(c_codec):  # noqa: F811 - imported pytest fixture
    c_codec.iris_console_frame_encode.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.POINTER(CWireHeader), ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t, ctypes.c_bool, ctypes.POINTER(ctypes.c_size_t),
    ]
    c_codec.iris_console_frame_encode.restype = ctypes.c_int32
    c_codec.iris_console_frame_decode.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_bool,
        ctypes.POINTER(CDecodedFrame),
    ]
    c_codec.iris_console_frame_decode.restype = ctypes.c_int32
    return c_codec


def decode_c(codec, wire, *, request=False):
    buffer = (ctypes.c_uint8 * len(wire)).from_buffer_copy(wire)
    decoded = CDecodedFrame()
    status = codec.iris_console_frame_decode(buffer, len(buffer), request, ctypes.byref(decoded))
    if status:
        return status, None
    h = decoded.header
    return status, Frame(channel=h.channel, type=h.type, flags=h.flags,
        session_id=h.session_id, request_id=h.request_id, stream_id=h.stream_id,
        sequence=h.sequence, payload=ctypes.string_at(decoded.payload, h.payload_size))


@pytest.mark.parametrize("is_request", [False, True])
@pytest.mark.parametrize("size", [0, 1, 2, 3, 511, 512, 513, MAX_PAYLOAD])
def test_console_matches_c_for_boundaries_and_all_byte_values(console_codec, is_request, size):
    frame = Frame(channel=0, type=3, session_id=19, request_id=42,
                  sequence=7, payload=bytes(n % 256 for n in range(size)))
    header = CWireHeader(channel=frame.channel, type=frame.type,
        session_id=frame.session_id, request_id=frame.request_id,
        sequence=frame.sequence, payload_size=size)
    output = (ctypes.c_uint8 * MAX_RECORD)()
    payload = (ctypes.c_uint8 * size).from_buffer_copy(frame.payload)
    output_size = ctypes.c_size_t()
    assert console_codec.iris_console_frame_encode(output, len(output),
        ctypes.byref(header), payload, size, is_request, ctypes.byref(output_size)) == 0
    expected = encode_record(frame, request=is_request)
    assert bytes(output[:output_size.value]) == expected
    assert all(32 <= c <= 126 or c in (10, 13) for c in expected)
    assert decode_record(expected, request=is_request) == frame
    assert decode_c(console_codec, expected, request=is_request) == (0, frame)
    assert decode_c(console_codec, expected[:-2], request=is_request) == (0, frame)


def test_logs_and_responses_survive_arbitrary_fragmentation():
    frame = Frame(channel=0, type=8, request_id=123, payload=b"status\0")
    boot = b"ESP-ROM:boot\r\nI boot: starting\n\xffpanic\n"
    app = b"I app: ready\r\n"
    data = boot + encode_record(frame, request=False) + app
    for width in [1, 2, 7, 83, len(data)]:
        decoder = ConsoleDecoder()
        records = []
        for offset in range(0, len(data), width):
            records.extend(decoder.feed(data[offset:offset+width]))
        assert [x for x in records if isinstance(x, Frame)] == [frame]
        assert b"".join(x for x in records if isinstance(x, bytes)) == boot + app
        assert decoder.finish() == b""
        assert decoder.invalid_records == 0


def test_overlong_input_is_bounded_preserved_and_recovers():
    decoder = ConsoleDecoder()
    noise = RESPONSE_PREFIX + b"x" * (MAX_RECORD * 3) + b"\n"
    frame = Frame(channel=0, type=3, request_id=42)
    records = decoder.feed(noise + encode_record(frame, request=False))
    assert b"".join(x for x in records if isinstance(x, bytes)) == noise
    assert records[-1] == frame
    assert decoder.invalid_records == 1
    assert len(decoder._buffer) < MAX_RECORD


@pytest.mark.parametrize("suffix", [b"!===", b"AB==", b"AAB=", b"AA=A",
    b"AA==AAAA", b"AAA", b"AAAA ", b"AAAA\x00", b"AAAA\nAAAA", b"===="])
def test_invalid_encoding_rejected_by_both_implementations(console_codec, suffix):
    record = RESPONSE_PREFIX + suffix + b"\n"
    with pytest.raises(ProtocolError):
        decode_record(record)
    assert decode_c(console_codec, record)[0] != 0


def test_corrupt_record_remains_in_raw_log_and_does_not_hide_following_frame():
    good = Frame(channel=0, type=3, payload=b"valid")
    bad = RESPONSE_PREFIX + b"broken!\n"
    decoder = ConsoleDecoder()
    assert decoder.feed(bad + encode_record(good, request=False)) == [bad, good]
    assert decoder.invalid_records == 1
    assert decoder.feed(b"partial boot") == []
    assert decoder.finish() == b"partial boot"


def test_01_wire_is_rejected_even_inside_valid_printable_record(console_codec):
    archive = pathlib.Path(__file__).resolve().parents[2] / "protocol/archive/0.1/golden_vectors.json"
    for vector in json.loads(archive.read_text())["vectors"]:
        old = bytes.fromhex(vector["wire_hex"])
        record = RESPONSE_PREFIX + base64.b64encode(old) + b"\n"
        with pytest.raises(ProtocolError):
            decode_record(record)
        assert decode_c(console_codec, record)[0] != 0


def test_console_decoder_fuzz_never_loses_raw_bytes_before_valid_record():
    rng = random.Random(0x202)
    expected = Frame(channel=0, type=3, request_id=128, payload=b"recovered")
    for _ in range(150):
        noise = bytes(rng.randrange(256) for _ in range(rng.randrange(7000))) + b"\n"
        decoder = ConsoleDecoder()
        records = decoder.feed(noise + encode_record(expected, request=False))
        assert records[-1] == expected
        assert b"".join(x for x in records[:-1] if isinstance(x, bytes)) == noise


def test_response_cannot_be_replayed_as_request(console_codec):
    record = encode_record(Frame(channel=0, type=3), request=False)
    with pytest.raises(ProtocolError):
        decode_record(record, request=True)
    assert decode_c(console_codec, record, request=True)[0] != 0
    assert not record.startswith(REQUEST_PREFIX)
