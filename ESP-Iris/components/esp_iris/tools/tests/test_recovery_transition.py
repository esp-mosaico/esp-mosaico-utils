import asyncio
from unittest.mock import AsyncMock

import pytest

from iris_gateway.gateway import GatewayService
from iris_gateway.operations import OperationOutcomeUnknown
from iris_gateway.recovery_transition import enter_recovery, recovery_preconditions


@pytest.mark.parametrize("bad", [{"unknown": 1}, {"recovery_version": ""}, {"partition_table_sha256": "abc"}, []])
def test_preconditions_are_strict(bad):
    with pytest.raises(ValueError):
        recovery_preconditions(bad)


def test_disconnect_during_transition_is_observed_without_replay():
    async def scenario():
        hub = AsyncMock()
        before = {"device_id": "d", "boot_id": 1, "firmware_mode": "normal"}
        after = {"device_id": "d", "boot_id": 2, "firmware_mode": "recovery"}
        hub.enter_recovery.side_effect = ConnectionError("response lost")
        hub.status.side_effect = [before, ConnectionError(), {**after, "device_id": "other"}, after]
        assert await enter_recovery(hub, "d") == after
        hub.enter_recovery.assert_awaited_once_with("d")
    asyncio.run(scenario())


def test_same_boot_cannot_complete_transition():
    async def scenario():
        hub = AsyncMock()
        hub.status.return_value = {"device_id": "d", "boot_id": 1, "firmware_mode": "recovery"}
        with pytest.raises(OperationOutcomeUnknown):
            await enter_recovery(hub, "d", before={"device_id": "d", "boot_id": 1, "firmware_mode": "normal"}, timeout=0.1)
        hub.enter_recovery.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("normal", [True, False])
@pytest.mark.parametrize("field", ["recovery_version", "partition_table_sha256"])
def test_precondition_mismatch_never_starts_ota_writer(normal, field):
    async def scenario():
        hub = AsyncMock()
        recovery = {"device_id": "d", "boot_id": 2, "firmware_mode": "recovery",
                    "chip_target": "esp32s31", "app_version": "0.1"}
        hub.status.side_effect = ([{**recovery, "boot_id": 1, "firmware_mode": "normal"}]
                                  if normal else []) + [recovery]
        hub.system_update_inventory.return_value = {"partition_table_sha256": "ab" * 32}
        service = GatewayService.__new__(GatewayService)
        service.hub, service.operations = hub, AsyncMock()
        required = {"recovery_version": "0.1", "partition_table_sha256": "ab" * 32}
        required[field] = "bad" if field == "recovery_version" else "cd" * 32
        with pytest.raises(ValueError, match="does not match"):
            await service.closed_loop_ota("d", b"firmware", {"chip_id": 0x20}, "op", preconditions=required)
        hub.ota_update.assert_not_called()
        assert hub.enter_recovery.await_count == int(normal)
    asyncio.run(scenario())
