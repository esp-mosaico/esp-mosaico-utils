"""Printable 0.2 console records; native logs need no Iris negotiation."""
from __future__ import annotations

import base64
import binascii

from .protocol import MAX_WIRE_FRAME, Frame, ProtocolError, decode_frame, encode_frame

REQUEST_PREFIX = b"iris @"
RESPONSE_PREFIX = b"@iris/0.2 "
HELLO_COMMAND = b"iris hello\n"
MAX_RECORD = len(RESPONSE_PREFIX) + 4 * ((MAX_WIRE_FRAME + 2) // 3) + 2


def encode_record(frame: Frame, *, request: bool = True) -> bytes:
    prefix = REQUEST_PREFIX if request else RESPONSE_PREFIX
    return prefix + base64.b64encode(encode_frame(frame)) + b"\r\n"


def decode_record(record: bytes, *, request: bool = False) -> Frame:
    if len(record) > MAX_RECORD:
        raise ProtocolError("console record exceeds the configured limit")
    prefix = REQUEST_PREFIX if request else RESPONSE_PREFIX
    if record.endswith(b"\n"):
        record = record[:-1]
    if record.endswith(b"\r"):
        record = record[:-1]
    if not record.startswith(prefix):
        raise ProtocolError("not an Iris 0.2 console record")
    encoded = record[len(prefix):]
    try:
        wire = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("invalid console base64") from exc
    if base64.b64encode(wire) != encoded:
        raise ProtocolError("non-canonical console base64")
    if not wire.endswith(b"\0") or len(wire) > MAX_WIRE_FRAME:
        raise ProtocolError("invalid console frame boundary")
    return decode_frame(wire[:-1])


class ConsoleDecoder:
    """Bounded line demultiplexer, preserving non-protocol bytes in order.

    Raw input must also be captured before parsing so a broken or overlong
    machine record cannot hide boot evidence. No binary protocol auto-probing.
    """

    def __init__(self, *, request: bool = False) -> None:
        self.request = request
        self.invalid_records = 0
        self._buffer = bytearray()
        self._overlong = False

    def feed(self, data: bytes) -> list[Frame | bytes]:
        records: list[Frame | bytes] = []
        prefix = REQUEST_PREFIX if self.request else RESPONSE_PREFIX
        # Work in bounded pieces even if a caller hands us megabytes of noise.
        for value in data:
            self._buffer.append(value)
            if value == 10:
                record = bytes(self._buffer)
                self._buffer.clear()
                if not self._overlong and record.startswith(prefix):
                    try:
                        records.append(decode_record(record, request=self.request))
                    except ProtocolError:
                        self.invalid_records += 1
                        records.append(record)
                else:
                    records.append(record)
                self._overlong = False
            elif len(self._buffer) >= MAX_RECORD:
                if not self._overlong and self._buffer.startswith(prefix):
                    self.invalid_records += 1
                records.append(bytes(self._buffer))
                self._buffer.clear()
                self._overlong = True
        return records

    def finish(self) -> bytes:
        remainder = bytes(self._buffer)
        self._buffer.clear()
        self._overlong = False
        return remainder
