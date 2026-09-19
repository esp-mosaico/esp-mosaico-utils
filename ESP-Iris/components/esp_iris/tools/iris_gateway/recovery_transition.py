"""One Recovery transition state machine for standalone, OTA and system updates."""
from __future__ import annotations

import asyncio
import re
from typing import Any

from .operations import OperationOutcomeUnknown, OperationRejected

CAPABILITY = "recovery-preconditions/v1"


def recovery_preconditions(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"recovery_version", "partition_table_sha256"}:
        raise ValueError("unknown Recovery precondition")
    result = dict(value)
    if "recovery_version" in result and (not isinstance(result["recovery_version"], str)
                                         or not 1 <= len(result["recovery_version"]) <= 64):
        raise ValueError("Recovery version must be a nonempty short string")
    if "partition_table_sha256" in result:
        digest = result["partition_table_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ValueError("partition table precondition must be a SHA-256")
        result["partition_table_sha256"] = digest.lower()
    return result


async def enter_recovery(hub: Any, device_id: str, *, before: dict[str, Any] | None = None,
                         timeout: float = 30, progress: Any = None) -> dict[str, Any]:
    before = before if before is not None else await hub.status(device_id)
    if before.get("device_id") != device_id:
        raise ValueError("Recovery transition requires the selected Device ID")
    if before.get("firmware_mode") == "recovery":
        return before
    previous_boot = before.get("boot_id")
    if previous_boot in (None, ""):
        raise ValueError("Recovery transition requires a live Boot ID")

    async def report(stage: str, **fields: Any) -> None:
        if progress is not None:
            await progress(stage, **fields)

    await report("entering_recovery", previous_boot_id=previous_boot)
    try:
        await hub.enter_recovery(device_id)
    except (ConnectionError, OSError):
        # A disconnect can win the race with the accepted response. Observe
        # only; never replay the transition or select another device.
        pass
    await report("waiting_recovery", previous_boot_id=previous_boot)
    deadline = asyncio.get_running_loop().time() + min(30, max(0.1, timeout))
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
        try:
            candidate = await hub.status(device_id)
        except (ConnectionError, OSError, KeyError, LookupError, RuntimeError):
            continue
        boot = candidate.get("boot_id")
        if (candidate.get("device_id") == device_id and candidate.get("firmware_mode") == "recovery"
                and boot not in (None, "") and str(boot) != str(previous_boot)):
            await report("recovery_connected", recovery_boot_id=boot)
            return candidate
    raise OperationOutcomeUnknown("Recovery transition outcome is unknown: the same device did not reconnect with a new Boot ID")


async def validate_recovery(hub: Any, device_id: str, status: dict[str, Any],
                            preconditions: dict[str, str]) -> dict[str, Any]:
    expected = recovery_preconditions(preconditions)
    if not expected:
        return {}
    if status.get("device_id") != device_id or status.get("firmware_mode") != "recovery":
        raise ValueError("Recovery preconditions require the selected device in Recovery")
    if "recovery_version" in expected and status.get("app_version") != expected["recovery_version"]:
        raise ValueError("Live Recovery version does not match the required product version")
    evidence = {"device_id": device_id, "boot_id": status.get("boot_id"),
                "recovery_version": status.get("app_version")}
    if "partition_table_sha256" in expected:
        inventory = await hub.system_update_inventory(device_id)
        actual = str(inventory.get("partition_table_sha256", "")).lower()
        if actual != expected["partition_table_sha256"]:
            raise OperationRejected(
                "Device partition table does not match the application build; use system update for layout changes",
                code="partition_layout_mismatch", device_id=device_id,
                current_sha256=actual, target_sha256=expected["partition_table_sha256"],
                recommended_action="system_update", write_started=False,
            )
        evidence["partition_table_sha256"] = actual
    return evidence
