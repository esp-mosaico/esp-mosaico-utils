from __future__ import annotations

import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_hub import SupervisorLink
from test_project_ownership import D, E, registry
from test_usb_ownership import until

from iris_gateway.gateway import GatewayService, create_app
from iris_gateway.hub import IrisHub
from iris_gateway.link import TcpLink
from iris_gateway.project_gateway import ProjectGateway
from iris_gateway.security import Actor
from iris_gateway.store import GatewayStore


@contextlib.asynccontextmanager
async def gateways(tmp_path):
    projects, clients = [], []
    opened = []

    async def open_link(host, port, **kwargs):
        link = SupervisorLink(len(opened) + 1, endpoint=f"tcp:{host}:{port}")
        opened.append(link)
        return link

    try:
        with patch.object(TcpLink, "open", side_effect=open_link), \
                patch("iris_gateway.device_selection.discover_iris_usb_devices", return_value=[]):
            for name in ("owner", "receiver", "contender"):
                reg = registry(tmp_path / "registry", name)
                store = GatewayStore(tmp_path / name)
                service = GatewayService(store, instance_id=name)
                hub = IrisHub(name, ownership=reg, event_sink=service.on_device_event)
                service.attach_hub(hub)
                project = ProjectGateway(reg, service, hub, asyncio.Event())
                service.project = project
                projects.append(project)
                client = TestClient(TestServer(create_app(service)))
                clients.append(client)
                await client.start_server()
                reg.set_url(str(client.make_url("")).rstrip("/"))
            await projects[0].acquire({"endpoint": E})
            yield projects, clients, opened
    finally:
        for client in clients:
            await client.close()
        for project in projects:
            await project.service.operations.close()
            await project.hub.close()
            project.registry.close(clean=True)
            project.service.store.close()


@pytest.mark.parametrize("selector", [{"device_id": D}, {"endpoint": E}])
def test_receiver_initiates_idle_handoff_with_live_monitor_and_idempotent_retry(tmp_path, selector):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            owner.clients.register({"kind": "workbench"}, connected=True)
            owner.clients.register({"kind": "run"}, connected=True)
            owner.streams = 1  # An existing log SSE stream is passive.
            with patch("iris_gateway.project_gateway.active_workers", return_value=[
                {"resources": [D], "operation_id": "external"},
            ]):
                assert owner.keepalive_reasons()["host_workers"] == 1
                assert receiver.keepalive_reasons()["host_workers"] == 0
            body = {**selector, "takeover_id": str(uuid.uuid4())}
            response = await clients[1].post("/v2/project/takeovers", json=body)
            result = await response.json()
            assert response.status == 200, result
            assert result["takeover"]["state"] == "completed"
            assert receiver.registry.claim("device:" + D)["owner"] == "receiver"
            assert len(opened) == 2 and opened[0].closed
            assert not owner.closing and len(owner.clients.clients) == 2
            response = await clients[1].post("/v2/project/takeovers", json=body)
            assert await response.json() == result
            assert len(opened) == 2
            owner.streams = 0
    asyncio.run(scenario())


def test_force_waits_for_write_cancels_queue_and_stops_mirrors_jobs(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            actor = Actor("local", "test")
            gate = asyncio.Event()
            first, _ = await owner.service.operations.submit(D, actor, "firmware.ota", {}, gate.wait)
            await until(lambda: bool(owner.service.operations.queue_state(D)["running"]))
            queued_call = AsyncMock()
            queued, _ = await owner.service.operations.submit(D, actor, "device.restart", {}, queued_call)
            for channel in (3, 4, 5):
                owner.hub._mirror_states[D, channel] = {}

            async def mirror_stop(device_id, channel):
                assert gate.is_set(), "no control commands during the active write"
                owner.hub._mirror_states.pop((device_id, channel))

            owner.hub.mirror_stop = AsyncMock(side_effect=mirror_stop)
            owner.observe({"kind": "job", "device_id": D, "job_id": 7, "job_state": "running"})
            owner.hub.job = AsyncMock(side_effect=[
                {"job_id": 7, "job_state": "running", "cancel_requested": True},
                {"job_id": 7, "job_state": "cancelled"},
            ])
            body = {"device_id": D, "takeover_id": str(uuid.uuid4()), "timeout": 2}
            response = await clients[1].post("/v2/project/takeovers", json=body)
            assert response.status == 409
            result = await response.json()
            reasons = result["error"]["details"]["cause"]["details"]["busy_reasons"]
            assert {item["kind"] for item in reasons} == {"operation", "mirror", "job"}
            assert not owner.blocked and not gate.is_set()
            request = asyncio.create_task(clients[1].post("/v2/project/takeovers", json={**body, "force": True}))
            await until(lambda: D in owner.blocked)
            response = await clients[0].post(f"/v2/devices/{D}/restart", json={})
            assert response.status == 409
            response = await clients[0].post("/v2/project/acquire", json={"endpoint": E})
            assert response.status == 409
            # Work for another device continues through the normal operation queue.
            other = AsyncMock(return_value={"ok": True})
            await owner.service.operations.execute("another-device", actor, "rpc.call", {}, other)
            other.assert_awaited_once()
            assert not request.done() and not opened[0].closed
            assert owner.registry.claim("device:" + D)["owner"] == "owner"
            gate.set()
            response = await asyncio.wait_for(request, 3)
            assert response.status == 200, await response.text()
            assert receiver.registry.claim("device:" + D)["owner"] == "receiver"
            assert owner.service.store.operation(first["operation_id"])["status"] == "succeeded"
            assert owner.service.store.operation(queued["operation_id"])["status"] == "cancelled"
            queued_call.assert_not_called()
            assert owner.hub.mirror_stop.await_count == 3
            assert [call.kwargs["cancel"] for call in owner.hub.job.await_args_list] == [True, False]
            assert not owner.blocked and not owner.jobs
    asyncio.run(scenario())


@pytest.mark.parametrize("blocker", ["write", "job", "worker"])
def test_force_timeout_retains_owner_unblocks_admission_and_never_cancels_write(tmp_path, blocker):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner = projects[0]
            gate = asyncio.Event()
            if blocker == "write":
                operation, _ = await owner.service.operations.submit(
                    D, Actor("local", "test"), "host.recovery", {}, gate.wait, exclusive_resources=(D,))
                await until(lambda: bool(owner.service.operations.queue_state(D)["running"]))
            elif blocker == "job":
                owner.observe({"kind": "job", "device_id": D, "job_id": 7, "job_state": "running"})
                owner.hub.job = AsyncMock(return_value={"job_id": 7, "job_state": "running"})
            workers = [{"resources": [D], "operation_id": "external"}] if blocker == "worker" else []
            with patch("iris_gateway.project_gateway.active_workers", return_value=workers):
                response = await clients[1].post("/v2/project/takeovers", json={
                    "device_id": D, "takeover_id": str(uuid.uuid4()), "force": True, "timeout": 0.08,
                })
            assert response.status == 409, await response.text()
            cause = (await response.json())["error"]["details"]["cause"]
            assert cause["code"] == "handoff_timeout"
            assert cause["details"]["busy_reasons"]
            assert owner.registry.claim("device:" + D)["owner"] == "owner"
            assert not opened[0].closed and not owner.blocked
            if blocker == "write":
                assert owner.service.store.operation(operation["operation_id"])["status"] == "running"
                gate.set()
                await until(lambda: not owner.service.operations._pending)
                assert owner.service.store.operation(operation["operation_id"])["status"] == "succeeded"
    asyncio.run(scenario())


def test_receiver_rejects_reused_id_and_dead_owner(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, _):
            owner, receiver, _ = projects
            body = {"device_id": D, "takeover_id": str(uuid.uuid4())}
            response = await clients[1].post("/v2/project/takeovers", json=body)
            assert response.status == 200
            response = await clients[2].post("/v2/project/takeovers", json=body)
            assert response.status == 409
            assert receiver.registry.claim("device:" + D)["owner"] == "receiver"
            with patch.object(owner.registry, "alive", return_value=False):
                response = await clients[0].post("/v2/project/takeovers", json={"device_id": D})
            assert response.status == 409
            assert not owner.hub.list_devices()
    asyncio.run(scenario())


def test_public_transfer_routes_are_removed(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, _):
            for path in ("transfer", "prepare", "accept", "abort", "reconcile-transfer", "takeover"):
                response = await clients[0].post("/v2/project/" + path, json={})
                assert response.status == 404, path
            response = await clients[0].get("/v2/project/transfers/" + str(uuid.uuid4()))
            assert response.status == 404
            response = await clients[1].post("/v2/project/takeovers", json={
                "device_id": D, "transfer_id": str(uuid.uuid4()),
            })
            assert response.status == 400
            assert projects[0].registry.claim("device:" + D)["owner"] == "owner"
    asyncio.run(scenario())


def test_status_and_resume_after_receiver_validation_was_interrupted(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            takeover_id = str(uuid.uuid4())
            path = "/v2/project/takeovers/" + takeover_id
            with patch.object(receiver, "accept", side_effect=RuntimeError("validation interrupted")):
                response = await clients[1].post("/v2/project/takeovers", json={
                    "device_id": D, "takeover_id": takeover_id,
                })
            assert response.status == 409
            response = await clients[1].get(path)
            record = (await response.json())["takeover"]
            assert record["takeover_id"] == takeover_id and record["state"] == "offered"
            assert "transfer_id" not in record
            response = await clients[2].post(path + "/resume", json={})
            assert response.status == 409
            response = await clients[1].post(path + "/resume", json={})
            assert response.status == 200, await response.text()
            completed = await response.json()
            assert completed["takeover"]["state"] == "completed"
            response = await clients[1].post(path + "/resume", json={})
            assert await response.json() == completed
            assert len(opened) == 2
            response = await clients[0].post(path + "/abort", json={})
            assert response.status == 409
            assert receiver.registry.claim("device:" + D)["owner"] == "receiver"
            assert not opened[-1].closed
            assert not owner.closing
    asyncio.run(scenario())


def test_abort_restores_original_owner_without_repeating_device_detach(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            takeover_id = str(uuid.uuid4())
            path = "/v2/project/takeovers/" + takeover_id
            with patch.object(receiver, "accept", side_effect=RuntimeError("validation interrupted")):
                response = await clients[1].post("/v2/project/takeovers", json={
                    "device_id": D, "takeover_id": takeover_id,
                })
            assert response.status == 409
            response = await clients[1].post(path + "/abort", json={})
            assert response.status == 409  # Only the original owner may roll back.
            response = await clients[0].post(path + "/abort", json={})
            assert response.status == 200
            aborted = await response.json()
            assert aborted["takeover"]["state"] == "aborted"
            await owner.acquire({"device_id": D})
            response = await clients[0].post(path + "/abort", json={})
            assert await response.json() == aborted
            assert len(opened) == 2 and not opened[-1].closed
            response = await clients[1].post(path + "/resume", json={})
            assert response.status == 409
            assert owner.registry.claim("device:" + D)["owner"] == "owner"
    asyncio.run(scenario())


def test_reconcile_takeover_requires_dead_participants_and_restores_ownership(tmp_path):
    async def scenario():
        from iris_gateway.ownership import OwnershipRegistry

        root = tmp_path / "registry"
        first, second = (registry(root, name) for name in ("a", "b"))
        takeover_id = str(uuid.uuid4())
        first.acquire(E, {})
        first.bind(E, D)
        first.prepare(D, "b", takeover_id)
        first.offer(takeover_id)
        first.close()
        second.close()
        reg = OwnershipRegistry(root)
        reg.register("b-new", "b", "/projects/b", "new-instance")
        store = GatewayStore(tmp_path / "store")
        service = GatewayService(store, instance_id="b-new")
        hub = IrisHub("b-new", ownership=reg)
        service.attach_hub(hub)
        service.project = ProjectGateway(reg, service, hub, asyncio.Event())
        client = TestClient(TestServer(create_app(service)))
        await client.start_server()
        try:
            path = "/v2/project/takeovers/" + takeover_id + "/reconcile"
            with patch.object(reg, "alive", return_value=True):
                response = await client.post(path, json={})
                assert response.status == 409
            response = await client.post(path, json={})
            assert response.status == 200, await response.text()
            result = await response.json()
            assert result["takeover"]["metadata"]["reconciled_by"] == "b-new"
            assert reg.claim("device:" + D)["owner"] == "b-new"
            response = await client.post(path, json={})
            assert await response.json() == result
        finally:
            await client.close()
            await hub.close()
            reg.close(clean=True)
            store.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("selector", [{"device_id": D}, {"endpoint": E},
                                       {"endpoint": "tcp:other-interface:19772"},
                                       {"device_id": D, "endpoint": "tcp:other-interface:19772"}])
def test_acquire_automatically_hands_off_idle_owner_without_grace_delay(tmp_path, selector):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            assert owner.clients.snapshot(owner.keepalive_reasons())["idle_remaining_seconds"] > 0
            response = await clients[1].post("/v2/project/acquire", json=selector)
            result = await response.json()
            assert response.status == 200, result
            assert result["device"]["device_id"] == D
            assert result["device"]["endpoint"] == selector.get("endpoint", E)
            assert receiver.registry.claim("device:" + D)["owner"] == "receiver"
            assert opened[0].closed and not owner.closing
            assert not owner.hub.list_devices()
            # An immediate switch back works while both Gateway processes live.
            response = await clients[0].post("/v2/project/acquire", json={"endpoint": E})
            assert response.status == 200, await response.text()
            assert owner.registry.claim("device:" + D)["owner"] == "owner"
    asyncio.run(scenario())


@pytest.mark.parametrize("blocker", ["client", "operation", "worker", "job", "mirror", "request", "stream"])
def test_automatic_handoff_retains_active_owner(tmp_path, blocker):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            gate = asyncio.Event()
            if blocker == "client":
                owner.clients.register({"kind": "workbench"}, connected=True)
            elif blocker == "operation":
                await owner.service.operations.submit(D, Actor("local", "test"), "firmware.ota", {}, gate.wait)
                await until(lambda: bool(owner.service.operations.queue_state(D)["running"]))
            elif blocker == "job":
                owner.observe({"kind": "job", "device_id": D, "job_id": 7, "job_state": "running"})
            elif blocker == "mirror":
                owner.hub._mirror_states[D, 3] = {}
            elif blocker == "request":
                owner.active[D] += 1
            elif blocker == "stream":
                owner.streams += 1
            workers = [{"resources": [D], "operation_id": "external"}] if blocker == "worker" else []
            try:
                with patch("iris_gateway.project_gateway.active_workers", return_value=workers):
                    response = await clients[1].post("/v2/project/acquire", json={"endpoint": E})
                result = await response.json()
                assert response.status == 409, result
                cause = result["error"]["details"]["cause"]
                assert cause["code"] == "owner_active"
                assert cause["details"]["owner"]["session_id"] == "owner"
                assert owner.registry.claim("device:" + D)["owner"] == "owner"
                assert not opened[0].closed and not owner.blocked
                assert not receiver.hub.list_devices()
            finally:
                gate.set()
                owner.active.clear()
                owner.streams = 0
                await until(lambda: not owner.service.operations._pending)
    asyncio.run(scenario())


def test_automatic_handoff_rechecks_client_registered_after_peer_status(tmp_path):
    async def scenario():
        from iris_gateway.takeover import peer_state
        async with gateways(tmp_path) as (projects, clients, opened):
            owner = projects[0]
            async def register_after_status(client, session):
                state = await peer_state(client, session)
                if session["session_id"] == "owner":
                    owner.clients.register({"kind": "cli"}, connected=True)
                return state
            with patch("iris_gateway.takeover.peer_state", side_effect=register_after_status):
                response = await clients[1].post("/v2/project/acquire", json={"endpoint": E})
            assert response.status == 409, await response.text()
            assert owner.registry.claim("device:" + D)["state"] == "owned"
            assert not opened[0].closed
    asyncio.run(scenario())


def test_failed_handoff_identity_keeps_all_endpoints_reserved(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, _):
            _, receiver, _ = projects
            endpoint = "tcp:new-interface:19772"
            with patch.object(receiver.hub, "connect_owned", side_effect=ConnectionError("device rebooting")):
                response = await clients[1].post("/v2/project/acquire", json={"device_id": D, "endpoint": endpoint})
            assert response.status != 200
            claim = receiver.registry.claim(endpoint)
            assert claim["state"] == "accepting" and claim["owner"] == "receiver"
            transfer = receiver.registry.transfer(claim["transfer_id"])
            assert endpoint in {item["resource"] for item in transfer["metadata"]["endpoints"]}
            assert transfer["metadata"]["preferred_endpoint"]["resource"] == endpoint
            response = await clients[2].post("/v2/project/acquire", json={"endpoint": endpoint})
            assert response.status == 409
            response = await clients[1].post("/v2/project/takeovers/" + claim["transfer_id"] + "/resume", json={})
            assert response.status == 200, await response.text()
            assert receiver.hub.list_devices()[0]["endpoint"] == endpoint
    asyncio.run(scenario())


@pytest.mark.parametrize("busy", [False, True])
def test_explicit_owned_endpoint_switch_stops_old_supervisor_and_protects_work(tmp_path, busy):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner = projects[0]
            endpoint = "tcp:alternate-control:19772"
            owner.registry.acquire(endpoint, {"endpoint": endpoint})
            owner.registry.bind(endpoint, D)
            if busy:
                owner.active[D] += 1
            try:
                response = await clients[0].post("/v2/project/acquire", json={"device_id": D, "endpoint": endpoint})
                assert response.status == (409 if busy else 200), await response.text()
                if busy:
                    assert not opened[0].closed
                    assert owner.hub.list_devices()[0]["endpoint"] == E
                else:
                    assert opened[0].closed
                    assert owner.hub.list_devices()[0]["endpoint"] == endpoint
                    assert E not in owner.hub._endpoint_tasks
                    response = await clients[0].post("/v2/project/acquire", json={"endpoint": E})
                    assert response.status == 200, await response.text()
                    assert owner.hub.list_devices()[0]["endpoint"] == E
                    assert opened[1].closed
            finally:
                owner.active.clear()
    asyncio.run(scenario())


def test_known_interface_handoff_releases_old_control_before_opening_new_port(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner, receiver, _ = projects
            endpoint = "tcp:known-interface:19772"
            claim = owner.registry.acquire(endpoint, {"endpoint": endpoint})
            owner.registry.bind(endpoint, D)
            owner.registry.release_attempt(endpoint, claim["generation"], remove_device=False)
            assert owner.registry.claim(endpoint) is None
            original_connect = receiver.hub.connect_owned
            async def connect_after_release(*args, **kwargs):
                assert opened[0].closed, "firmware cannot answer a second control interface yet"
                await original_connect(*args, **kwargs)
            with patch.object(receiver.hub, "connect_owned", side_effect=connect_after_release):
                response = await clients[1].post("/v2/project/acquire", json={"endpoint": endpoint})
            assert response.status == 200, await response.text()
            assert receiver.hub.list_devices()[0]["endpoint"] == endpoint
    asyncio.run(scenario())


def test_device_id_handoff_keeps_current_interface_instead_of_first_historical_claim(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            endpoint = "tcp:currently-selected:19772"
            response = await clients[0].post("/v2/project/acquire", json={"device_id": D, "endpoint": endpoint})
            assert response.status == 200, await response.text()
            response = await clients[1].post("/v2/project/acquire", json={"device_id": D})
            assert response.status == 200, await response.text()
            assert projects[1].hub.list_devices()[0]["endpoint"] == endpoint
            assert opened[0].closed and opened[1].closed
    asyncio.run(scenario())


def test_automatic_handoff_requires_owner_idle_capability(tmp_path):
    async def scenario():
        async with gateways(tmp_path) as (projects, clients, opened):
            owner = projects[0]
            snapshot = owner.snapshot
            def old_snapshot(**kwargs):
                result = snapshot(**kwargs)
                result["capabilities"] = ["device-takeover/v1"]
                return result
            with patch.object(owner, "snapshot", side_effect=old_snapshot):
                response = await clients[1].post("/v2/project/acquire", json={"endpoint": E})
            assert response.status == 409
            assert owner.registry.claim("device:" + D)["owner"] == "owner"
            assert not opened[0].closed
    asyncio.run(scenario())
