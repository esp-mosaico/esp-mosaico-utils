"""Device identity and capabilities advertised by the session handshake."""
from __future__ import annotations

import dataclasses
from typing import Any

from .boot_identity import boot_id_text
from .protocol import Capability


@dataclasses.dataclass
class DeviceInfo:
    device_id: str
    boot_id: int
    session_id: int
    endpoint: str
    transport: int
    project_name: str
    app_version: str
    idf_version: str
    firmware_sha256: str
    reset_reason: int
    capabilities: int
    auth_mode: int
    max_payload: int
    firmware_mode: str = "unknown"
    product_contract: str = ""
    chip_target: str = ""
    board_id: str = ""
    layout_id: str = ""
    recovery_abi: int = 0
    required_features: int = 0
    health_timeout_ms: int = 45000
    hardware_mac: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = boot_id_text(dataclasses.asdict(self))
        bits = {
            0: "log",
            1: "events",
            2: "status",
            3: "time_sync",
            4: "screen",
            5: "ota",
            6: "crash",
            7: "auth",
            8: "rpc",
            9: "jobs",
            10: "image",
            11: "audio",
            12: "mirror",
            13: "files",
            14: "ota_project_name_match",
            15: "system_update",
            16: "system_inventory",
            19: "task_memory",
        }
        names = [name for bit, name in bits.items() if self.capabilities & (1 << bit)]
        names.append("restart")
        if "rpc" in names:
            names.append("input")
        result["capability_names"] = names
        result["ota_project_name_match_required"] = bool(
            self.capabilities & Capability.OTA_PROJECT_NAME_MATCH
        )
        return result
