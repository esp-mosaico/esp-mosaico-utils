"""Decode read-only status and crash observations from a concrete device session."""
from __future__ import annotations

from typing import Any

from .device_info import DeviceInfo
from .protocol import ProtocolError, TlvTag, tlv_u8, tlv_u32, tlv_u64


def decode_status(fields: dict[int, bytes], info: DeviceInfo) -> dict[str, Any]:
    raw_hardware_mac = fields.get(int(TlvTag.HARDWARE_MAC), b"")
    if raw_hardware_mac:
        hardware_mac = ":".join(f"{byte:02x}" for byte in raw_hardware_mac)
        if hardware_mac != info.hardware_mac:
            raise ProtocolError("hardware MAC changed on a live session")
    return {
        **info.as_dict(),
        "uptime_us": tlv_u64(fields, TlvTag.UPTIME_US),
        "free_internal": tlv_u32(fields, TlvTag.FREE_INTERNAL),
        "min_free_internal": tlv_u32(fields, TlvTag.MIN_FREE_INTERNAL),
        "total_internal": tlv_u32(fields, TlvTag.TOTAL_INTERNAL),
        "total_spiram": tlv_u32(fields, TlvTag.TOTAL_SPIRAM),
        "free_spiram": tlv_u32(fields, TlvTag.FREE_SPIRAM),
        "min_free_spiram": tlv_u32(fields, TlvTag.MIN_FREE_SPIRAM),
        "log_dropped_bytes": tlv_u32(fields, TlvTag.LOG_DROPPED),
        "rx_frames": tlv_u32(fields, TlvTag.RX_FRAMES),
        "tx_frames": tlv_u32(fields, TlvTag.TX_FRAMES),
        "invalid_frames": tlv_u32(fields, TlvTag.INVALID_FRAMES),
        "link_count": tlv_u32(fields, TlvTag.LINK_COUNT),
        "task_stack_free_min_bytes": tlv_u32(
            fields, TlvTag.TASK_STACK_FREE_MIN
        ),
        "worker_active_max_us": tlv_u32(
            fields, TlvTag.WORKER_ACTIVE_MAX_US
        ),
        "lifecycle_state": tlv_u8(fields, TlvTag.LIFECYCLE_STATE),
        "internal_heap_used_bytes": tlv_u32(
            fields, TlvTag.INTERNAL_HEAP_USED
        ),
        "static_internal_bytes": tlv_u32(
            fields, TlvTag.STATIC_INTERNAL_BYTES
        ),
        "internal_total_bytes": (
            tlv_u32(fields, TlvTag.STATIC_INTERNAL_BYTES)
            + tlv_u32(fields, TlvTag.INTERNAL_HEAP_USED)
        ),
        "crash_count": tlv_u32(fields, TlvTag.CRASH_COUNT),
        "crash_limit": tlv_u32(fields, TlvTag.CRASH_LIMIT),
        "crash_loop_triggered": bool(
            tlv_u8(fields, TlvTag.CRASH_LOOP_TRIGGERED)
        ),
        "crash_recovery_pending": bool(
            tlv_u8(fields, TlvTag.CRASH_RECOVERY_PENDING)
        ),
        "crash_origin_reset_reason": tlv_u32(
            fields, TlvTag.CRASH_ORIGIN_RESET_REASON
        ),
        "crash_failed_app_address": tlv_u32(
            fields, TlvTag.CRASH_FAILED_APP_ADDRESS
        ),
        "crash_failed_boot_id": tlv_u64(
            fields, TlvTag.CRASH_FAILED_BOOT_ID
        ),
        "crash_failed_firmware_sha256": fields.get(
            int(TlvTag.CRASH_FAILED_FIRMWARE_SHA256), b""
        ).hex(),
        "crash_state_error": tlv_u32(fields, TlvTag.CRASH_STATE_ERROR),
    }


def decode_crash_report(
    fields: dict[int, bytes], info: DeviceInfo, chunk_max: int,
) -> dict[str, Any]:
    core_sha = fields.get(int(TlvTag.CORE_DUMP_ELF_SHA256), b"").decode(
        "ascii", errors="replace"
    )
    sha_matches = bool(core_sha) and info.firmware_sha256.startswith(core_sha)
    sha_complete = bool(tlv_u8(fields, TlvTag.CORE_DUMP_ELF_SHA256_COMPLETE))
    return {
        "device_id": info.device_id,
        "boot_id": tlv_u64(fields, TlvTag.BOOT_ID, info.boot_id),
        "session_id": info.session_id,
        "reset_reason": tlv_u32(fields, TlvTag.RESET_REASON),
        "previous_boot_crash": bool(
            tlv_u8(fields, TlvTag.PREVIOUS_BOOT_CRASH)
        ),
        "crash_count": tlv_u32(fields, TlvTag.CRASH_COUNT),
        "crash_limit": tlv_u32(fields, TlvTag.CRASH_LIMIT),
        "crash_loop_triggered": bool(
            tlv_u8(fields, TlvTag.CRASH_LOOP_TRIGGERED)
        ),
        "crash_recovery_pending": bool(
            tlv_u8(fields, TlvTag.CRASH_RECOVERY_PENDING)
        ),
        "crash_origin_reset_reason": tlv_u32(
            fields, TlvTag.CRASH_ORIGIN_RESET_REASON
        ),
        "crash_failed_app_address": tlv_u32(
            fields, TlvTag.CRASH_FAILED_APP_ADDRESS
        ),
        "crash_failed_boot_id": tlv_u64(
            fields, TlvTag.CRASH_FAILED_BOOT_ID
        ),
        "crash_failed_firmware_sha256": fields.get(
            int(TlvTag.CRASH_FAILED_FIRMWARE_SHA256), b""
        ).hex(),
        "crash_state_error": tlv_u32(fields, TlvTag.CRASH_STATE_ERROR),
        "core_dump_present": bool(tlv_u8(fields, TlvTag.CORE_DUMP_PRESENT)),
        "core_dump_valid": bool(tlv_u8(fields, TlvTag.CORE_DUMP_VALID)),
        "core_dump_size": tlv_u32(fields, TlvTag.CORE_DUMP_SIZE),
        "core_dump_chunk_max": chunk_max,
        "core_dump_elf_sha256": core_sha,
        "core_dump_elf_sha256_complete": sha_complete,
        "firmware_sha256": info.firmware_sha256,
        "firmware_sha_matches": sha_matches,
        "decode_eligible": sha_complete and sha_matches,
        "panic_reason": fields.get(int(TlvTag.PANIC_REASON), b"").decode(
            "utf-8", errors="replace"
        ),
    }
