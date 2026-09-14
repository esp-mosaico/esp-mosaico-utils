"""Combine heap and task reports for a single device boot."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from aiohttp import web

from .boot_identity import boot_id_text
from .contracts import GatewayHub


class MemoryGateway(Protocol):
    mode: str
    _memory_requests: dict[str, asyncio.Task[dict[str, Any]]]

    @property
    def device_hub(self) -> GatewayHub: ...

    def resolve_device(self, device_id: str) -> str: ...


async def memory_snapshot(
    service: MemoryGateway,
    device_id: str,
) -> dict[str, Any]:
    if service.mode != "develop":
        raise web.HTTPConflict(text="live memory polling requires develop mode")
    device_id = service.resolve_device(device_id)
    hub = service.device_hub
    requests = service._memory_requests
    pending = requests.get(device_id)
    if pending is None:
        async def sample() -> dict[str, Any]:
            status = boot_id_text(await hub.status(device_id))
            tasks = boot_id_text(await hub.task_memory(device_id))
            if tasks["device_id"] != device_id:
                raise web.HTTPConflict(text="device identity changed during memory snapshot")
            if tasks["boot_id"] != status["boot_id"]:
                raise web.HTTPConflict(text="device rebooted during memory snapshot")
            return {
                "device_id": device_id,
                "boot_id": status["boot_id"],
                "heap_uptime_us": status["uptime_us"],
                "task_uptime_us": tasks["uptime_us"],
                "total_internal_bytes": status["total_internal"],
                "free_internal_bytes": status["free_internal"],
                "min_free_internal_bytes": status["min_free_internal"],
                "total_spiram_bytes": status["total_spiram"],
                "free_spiram_bytes": status["free_spiram"],
                "min_free_spiram_bytes": status["min_free_spiram"],
                "tasks": tasks["tasks"],
            }

        pending = asyncio.create_task(sample())
        requests[device_id] = pending

        def forget(completed: asyncio.Task[dict[str, Any]]) -> None:
            if requests.get(device_id) is completed:
                requests.pop(device_id, None)

        pending.add_done_callback(forget)
    return await asyncio.shield(pending)
