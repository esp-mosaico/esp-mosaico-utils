from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from iris_gateway.gateway import GatewayService


class _MemoryHub:
    def __init__(self, boot_id: str) -> None:
        self.boot_id = boot_id
        self.task_queries = 0

    async def status(self, device_id: str) -> dict[str, object]:
        assert device_id == "device-1"
        return {
            "device_id": device_id,
            "boot_id": "42",
            "uptime_us": 100,
            "total_internal": 1000,
            "free_internal": 600,
            "min_free_internal": 400,
            "total_spiram": 2000,
            "free_spiram": 1500,
            "min_free_spiram": 1000,
        }

    async def task_memory(self, device_id: str) -> dict[str, object]:
        assert device_id == "device-1"
        self.task_queries += 1
        await asyncio.sleep(0)
        return {
            "device_id": device_id,
            "boot_id": self.boot_id,
            "uptime_us": 101,
            "tasks": [{"task_number": 7, "stack_free_min_bytes": 512}],
        }


class _MemoryService:
    mode = "develop"

    def __init__(self, boot_id: str) -> None:
        self.device_hub = _MemoryHub(boot_id)
        self._memory_requests = {}

    def resolve_device(self, device_id: str) -> str:
        return device_id


def test_memory_snapshot_keeps_heap_and_tasks_on_one_boot() -> None:
    snapshot = asyncio.run(GatewayService.memory_snapshot(_MemoryService("42"), "device-1"))
    assert snapshot["boot_id"] == "42"
    assert snapshot["min_free_spiram_bytes"] == 1000
    assert snapshot["tasks"] == [{"task_number": 7, "stack_free_min_bytes": 512}]

    with pytest.raises(web.HTTPConflict) as error:
        asyncio.run(GatewayService.memory_snapshot(_MemoryService("43"), "device-1"))
    assert "rebooted" in error.value.text


def test_concurrent_memory_clients_share_one_task_scan() -> None:
    async def scenario() -> None:
        service = _MemoryService("42")
        first, second = await asyncio.gather(
            GatewayService.memory_snapshot(service, "device-1"),
            GatewayService.memory_snapshot(service, "device-1"),
        )
        assert first == second
        assert service.device_hub.task_queries == 1

    asyncio.run(scenario())
