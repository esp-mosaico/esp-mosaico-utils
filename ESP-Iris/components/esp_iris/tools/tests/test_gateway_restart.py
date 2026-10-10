"""Restart acceptance must describe the requested boot, never replayed history."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from iris_gateway.gateway import GatewayService


def connection(boot):
    return {"kind": "connection", "connection_state": "rebooted", "boot_id": boot}


def status(boot, **kwargs):
    return {"device_id": "device-a", "boot_id": boot, "app_version": "1.0", **kwargs}


def test_restart_discards_replayed_boot_before_sending_request():
    async def scenario():
        queue = asyncio.Queue()
        queue.put_nowait(connection(41))

        async def restart(device_id, delay):
            assert queue.empty()
            queue.put_nowait(connection(43))
            return delay

        hub = SimpleNamespace(
            subscribe=Mock(return_value=queue), unsubscribe=Mock(),
            status=AsyncMock(side_effect=[status(42), status(43)]),
            restart=AsyncMock(side_effect=restart),
        )
        service = SimpleNamespace(demo=False, device_hub=hub,
                                  operations=SimpleNamespace(stage=AsyncMock()))
        result = await GatewayService.closed_loop_restart(service, "device-a", 250, "op")
        assert result["previous_boot_id"] == 42
        assert result["boot_id"] == 43
        hub.restart.assert_awaited_once_with("device-a", 250)
        hub.unsubscribe.assert_called_once_with("device-a", queue)

    asyncio.run(scenario())


@pytest.mark.parametrize("candidate", [
    status(42), status(43, device_id="different-device"), status(43, stale=True),
    ConnectionError("session closed"), KeyError("device disconnected"),
])
def test_restart_requires_live_identity_matching_reconnect_event(candidate):
    async def scenario():
        queue = asyncio.Queue()

        async def restart(device_id, delay):
            queue.put_nowait(connection(43))
            queue.put_nowait(connection(44))
            return delay

        hub = SimpleNamespace(
            subscribe=Mock(return_value=queue), unsubscribe=Mock(),
            status=AsyncMock(side_effect=[status(42), candidate, status(44)]),
            restart=AsyncMock(side_effect=restart),
        )
        service = SimpleNamespace(demo=False, device_hub=hub,
                                  operations=SimpleNamespace(stage=AsyncMock()))
        result = await GatewayService.closed_loop_restart(service, "device-a", 250, "op")
        assert result["boot_id"] == 44
        hub.restart.assert_awaited_once()
        hub.unsubscribe.assert_called_once_with("device-a", queue)

    asyncio.run(scenario())
