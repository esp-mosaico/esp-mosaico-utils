"""Final firmware contract acceptance shared by app and system updates."""
from __future__ import annotations

from typing import Any

from .compatibility import validate_update_compatibility


def validate_updated_contract(status: dict[str, Any], device_id: str, chip_id: Any,
                              expectation: dict[str, Any], *, role: str = "normal") -> None:
    if status.get("device_id") != device_id:
        raise ValueError("post-update Device ID does not match the selected device")
    if status.get("firmware_mode") != role:
        raise ValueError(f"post-update firmware role must be {role}; got {status.get('firmware_mode')!r}")
    validate_update_compatibility(status, chip_id, expectation, recovery=role == "recovery")
