from __future__ import annotations

import asyncio
import json
import pathlib
import re
import time
from typing import Any

from aiohttp import web

from .crash_diagnostics import decode_coredump


def matching_artifact(store: Any, report: dict[str, Any]) -> dict[str, Any] | None:
    core_sha = str(report.get("core_dump_elf_sha256", "")).lower()
    failed_sha = str(report.get("crash_failed_firmware_sha256", "")).lower()
    if report.get("core_dump_elf_sha256_complete"):
        expected_sha = core_sha
    elif (
        re.fullmatch(r"[0-9a-f]{64}", failed_sha)
        and len(core_sha) >= 8
        and failed_sha.startswith(core_sha)
    ):
        expected_sha = failed_sha
    else:
        return None
    return next(
        (
            artifact for artifact in store.firmware_artifacts()
            if str(artifact.get("elf_sha256", "")).lower() == expected_sha
        ),
        None,
    )


def archive_key(device_id: str, report: dict[str, Any]) -> str:
    failed_boot_id = int(report.get("crash_failed_boot_id") or 0)
    identity = str(failed_boot_id) if failed_boot_id else ":".join((
        str(report.get("core_dump_elf_sha256") or "unknown"),
        str(report.get("core_dump_size") or 0),
        str(report.get("panic_reason") or "unknown"),
    ))
    return f"crash.archive.{device_id}.{identity}"


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "source_location_confirmed": False,
        "incident_identity_confirmed": False,
    }


async def archive_evidence(service: Any, device_id: str) -> dict[str, Any]:
    report = await service.device_hub.crash_report(device_id)
    failed_boot_id = int(report.get("crash_failed_boot_id") or 0)
    setting_key = archive_key(device_id, report)
    existing = service.store.get_setting(setting_key)
    candidate = matching_artifact(service.store, report)
    existing_diagnosis = (
        existing.get("diagnosis") if isinstance(existing, dict) else None
    )
    retryable = (
        candidate is not None
        and isinstance(existing_diagnosis, dict)
        and existing_diagnosis.get("status") in {"unavailable", "failed"}
    )
    if isinstance(existing, dict) and not retryable:
        return existing

    crash_path = service.store.save_artifact(
        device_id,
        "crash-index",
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(),
        "json",
    )
    result: dict[str, Any] = {
        "status": "metadata_only",
        "device_id": device_id,
        "failed_boot_id": failed_boot_id,
        "crash_index": str(crash_path),
        "core_dump": None,
        "diagnosis": unavailable("no valid retained Core Dump"),
    }
    if report.get("core_dump_present") and report.get("core_dump_valid"):
        preserved = await service.preserve_coredump(device_id)
        if preserved is not None:
            result.update(status="preserved", core_dump=preserved)
            if candidate is None:
                result["diagnosis"] = unavailable(
                    "matching archived ELF is unavailable"
                )
            else:
                diagnosis, raw = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: decode_coredump(
                        pathlib.Path(str(preserved["path"])),
                        candidate,
                        expected_failed_boot_id=failed_boot_id,
                    ),
                )
                result["diagnosis"] = diagnosis
                result["candidate_artifact_id"] = candidate.get("artifact_id")
                if raw:
                    result["decoder_output"] = str(service.store.save_artifact(
                        device_id, "coredump-decoder", raw, "txt"
                    ))
                result["diagnosis_path"] = str(service.store.save_artifact(
                    device_id,
                    "crash-diagnosis",
                    (json.dumps(diagnosis, ensure_ascii=False, indent=2) + "\n").encode(),
                    "json",
                ))
    service.store.set_setting(setting_key, result)
    return result


async def auto_archive(service: Any, device_id: str) -> None:
    try:
        result = await archive_evidence(service, device_id)
        event = service.store.append_event(
            "device",
            {
                "kind": "device_event",
                "event_name": "crash_evidence_archived",
                "device_id": device_id,
                "archive": result,
                "host_receive_wall_ns": time.time_ns(),
            },
            device_id,
        )
        for queue in tuple(service._subscribers):
            if not queue.full():
                queue.put_nowait(event)
    except (
        ConnectionError, KeyError, LookupError, OSError,
        RuntimeError, TypeError, ValueError,
    ) as error:
        service.store.append_event(
            "system",
            {
                "kind": "crash_archive_failed",
                "device_id": device_id,
                "error": str(error),
                "host_receive_wall_ns": time.time_ns(),
            },
            device_id,
        )
    finally:
        service._crash_archives_in_progress.discard(device_id)


def register_routes(app: web.Application, service: Any) -> None:
    async def report(request: web.Request) -> web.Response:
        blocked = service.require_develop()
        if blocked is not None:
            return blocked
        device_id = service.resolve_device(request.match_info["device_id"])
        value = await service.device_hub.crash_report(device_id)
        candidate = matching_artifact(service.store, value)
        saved = service.store.get_setting(archive_key(device_id, value))
        value = {
            **value,
            "candidate_artifact_id": candidate.get("artifact_id") if candidate else None,
            "candidate_elf_sha256": candidate.get("elf_sha256") if candidate else None,
            "decode_eligible": bool(value.get("core_dump_valid") and candidate),
            "archive": saved if isinstance(saved, dict) else None,
        }
        return web.json_response({"reports": [value]})

    async def core_dump(request: web.Request) -> web.StreamResponse:
        blocked = service.require_develop()
        if blocked is not None:
            return blocked
        device_id = service.resolve_device(request.match_info["device_id"])
        artifact = await service.preserve_coredump(device_id)
        if artifact is None:
            raise KeyError("no valid retained coredump")
        return web.FileResponse(
            artifact["path"], headers={"X-ESP-Iris-SHA256": artifact["sha256"]}
        )

    async def archive(request: web.Request) -> web.Response:
        blocked = service.require_develop()
        if blocked is not None:
            return blocked
        device_id = service.resolve_device(request.match_info["device_id"])
        return web.json_response(await archive_evidence(service, device_id))

    app.router.add_get("/v1/devices/{device_id}/crashes", report)
    app.router.add_get("/v1/devices/{device_id}/crashes/core-dump", core_dump)
    app.router.add_post("/v1/devices/{device_id}/crashes/archive", archive)
