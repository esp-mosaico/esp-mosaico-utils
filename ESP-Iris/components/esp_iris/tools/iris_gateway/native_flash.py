"""Prepare native IDF commands without inspecting or building firmware.

IDF owns build dependencies, flash arguments, image validation and resets.
Gateway owns serial handoff and observes the console after the command exits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def prepare_native_flash(build_dir: Path, command: dict[str, Any], *,
                         target: str = "flash", endpoint: str | None = None,
                         device_id: str | None = None, baudrate: int | None = None,
                         reconnect_timeout: float = 10) -> dict[str, Any]:
    """Wrap a native command. ``build_dir`` is retained for API compatibility.

    No build output is required: the command may configure and build from scratch.
    Baud rate controls the resumed console, not IDF's flash baud rate.
    """
    if target not in {"flash", "app-flash"}:
        raise ValueError("native flash target must be flash or app-flash")
    if not endpoint and not device_id:
        raise ValueError("native flash requires an explicit endpoint or Device ID")
    if baudrate is None:
        baudrate = 115200
    if not 9600 <= baudrate <= 3000000 or not 0 <= reconnect_timeout <= 60:
        raise ValueError("invalid console baud rate or reconnect timeout")
    return {"action": "host.flash", "device_id": device_id, "endpoint": endpoint,
            "commands": [command], "flash_target": target, "baudrate": baudrate,
            "reconnect_timeout": reconnect_timeout}
