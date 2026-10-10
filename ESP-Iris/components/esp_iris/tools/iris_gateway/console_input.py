"""Validation shared by console adapters and the public HTTP entrypoint."""
from __future__ import annotations

import shlex

CONSOLE_LINE_MAX_BYTES = 255
CONSOLE_WRITE_TIMEOUT_SECONDS = 5.0


def encode_console_line(line: str) -> bytes:
    if not isinstance(line, str):
        raise TypeError("console line must be a string")
    encoded = line.encode("utf-8")
    if not line.strip() or not line.isprintable() or len(encoded) > CONSOLE_LINE_MAX_BYTES:
        raise ValueError(f"console line must contain 1 to {CONSOLE_LINE_MAX_BYTES} printable UTF-8 bytes")
    try:
        parts = shlex.split(line)
    except ValueError:
        # Custom product consoles may accept unmatched quotes as literal text.
        parts = line.strip().split(maxsplit=1)
    if len(parts) >= 2 and parts[0] == "iris" and (parts[1] == "hello" or parts[1].startswith("@")):
        raise ValueError("Iris discovery and protocol records are managed by Gateway; use iris help/status or the RPC API")
    return encoded + b"\n"
