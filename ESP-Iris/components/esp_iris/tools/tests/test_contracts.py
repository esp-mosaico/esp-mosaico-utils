from __future__ import annotations

import asyncio

from iris_gateway.contracts import GatewayHub
from iris_gateway.hub import IrisHub


def test_real_hub_satisfies_gateway_application_boundary() -> None:
    hub = IrisHub("contract-test")
    assert isinstance(hub, GatewayHub)


def test_hub_constructed_without_loop_serializes_concurrent_admissions(monkeypatch):
    previous_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    asyncio.set_event_loop(None)
    try:
        hub = IrisHub("admission-test")

        async def scenario():
            active = 0
            maximum = 0
            admitted = []

            async def bind(session):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0)
                admitted.append(session)
                active -= 1

            monkeypatch.setattr(hub, "_bind_ready", bind)
            await asyncio.gather(hub._on_ready("first"), hub._on_ready("second"))
            assert maximum == 1
            assert admitted == ["first", "second"]

        asyncio.run(scenario())
    finally:
        asyncio.set_event_loop_policy(previous_policy)
