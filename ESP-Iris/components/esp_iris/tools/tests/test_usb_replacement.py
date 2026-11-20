"""A reused USB location must not transfer the previous board's ownership."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import uuid
from unittest.mock import patch

import pytest
from test_hub import SupervisorLink
from test_project_ownership import D, E
from test_takeover import gateways
from test_usb_ownership import until

from iris_gateway.link import EndpointLock, SerialLink
from iris_gateway.ownership import OwnershipConflict
from iris_gateway.protocol import decode_frame, encode_frame
from iris_gateway.security import Actor
from iris_gateway.takeover import USB_REFRESH_CAPABILITY

B = "4553502d49524953010030eda0aaf494"
U = "usb:location=replacement-test"
OLD = {"path": "/dev/iris-test", "device_path": "/dev/iris-test",
       "location": "replacement-test", "vid": 0x303A, "pid": 0x4002,
       "serial_number": "30eda0aa1c7e", "link_role": "data"}
NEW = {**OLD, "serial_number": "30eda0aaf494"}


@contextlib.asynccontextmanager
async def replaced_usb(tmp_path):
    async with gateways(tmp_path) as (projects, clients, opened):
        owner = projects[0]
        owner.registry.acquire(U, OLD)
        owner.registry.bind(U, D)
        state = {"metadata": NEW, "identity": B, "links": []}

        async def open_usb(path, **kwargs):
            link = SupervisorLink(len(state["links"]) + 100, endpoint=kwargs["endpoint"])
            frame = decode_frame(link.incoming.get_nowait()[:-1])
            link.incoming.put_nowait(encode_frame(dataclasses.replace(
                frame, payload=frame.payload.replace(bytes.fromhex(D), bytes.fromhex(state["identity"])),
            )))
            state["links"].append(link)
            return link

        with contextlib.ExitStack() as patches:
            for module in ("hub", "takeover", "project_gateway"):
                patches.enter_context(patch(f"iris_gateway.{module}.resolve_usb_port",
                                            side_effect=lambda _: dict(state["metadata"])))
            patches.enter_context(patch.object(SerialLink, "open", side_effect=open_usb))
            yield projects, clients, opened, state


@pytest.mark.parametrize("action", ["acquire", "takeovers"])
@pytest.mark.parametrize("receiver", [0, 1])
@pytest.mark.parametrize("historical_only", [False, True])
def test_replacement_admits_new_hello_and_preserves_old_board(tmp_path, action, receiver, historical_only):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, state):
            owner = projects[0]
            generation = owner.registry.claim(U)["generation"]
            if historical_only:
                owner.registry.release_attempt(U, generation, remove_device=False)
            # Work on A's remaining interface must survive B's admission.
            gate = asyncio.Event()
            operation, _ = await owner.service.operations.submit(D, Actor("local", "test"), "test.write", {}, gate.wait)
            await until(lambda: bool(owner.service.operations.queue_state(D)["running"]))
            try:
                body = {"endpoint": U, **({"takeover_id": str(uuid.uuid4())} if action == "takeovers" else {})}
                response = await asyncio.wait_for(clients[receiver].post("/v2/project/" + action, json=body), 3)
                result = await response.json()
                assert response.status == 200, result
                assert result["device"]["device_id"] == B
                assert result["device"]["endpoint"] == U
                assert state["links"] and not state["links"][-1].closed
                assert owner.registry.claim(U)["device_id"] == B
                assert owner.registry.claim(U)["generation"] > generation
                assert owner.registry.claim("device:" + D)["owner"] == "owner"
                assert owner.registry.claim(E)["state"] == "owned"
                assert owner.hub.get(D).link is opened[0] and not opened[0].closed
                assert U not in {item["endpoint"] for item in owner.registry.known_endpoints(D)}
                assert owner.service.operations.queue_state(D)["running"] == [operation["operation_id"]]
                assert not gate.is_set()
                response = await clients[receiver].post("/v2/project/" + action, json=body)
                assert response.status == 200, await response.text()
                assert (await response.json())["device"]["device_id"] == B
                assert len(state["links"]) == 1
            finally:
                gate.set()
                await until(lambda: not owner.service.operations.queue_state(D)["running"])
    asyncio.run(scenario())


@pytest.mark.parametrize("other_endpoint", [False, True])
def test_supervisor_retires_replaced_endpoint_before_opening_it(tmp_path, other_endpoint):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, state):
            owner = projects[0]
            generation = owner.registry.claim(U)["generation"]
            if not other_endpoint:
                other_generation = owner.registry.claim(E)["generation"]
                await owner.hub.disconnect_owned_endpoint(E)
                owner.registry.release_attempt(E, other_generation, remove_device=False)
            await owner.hub.connect_owned(U, OLD)
            await until(lambda: owner.hub._endpoint_tasks[U].done())
            assert owner.registry.claim(U) is None
            assert not state["links"]
            assert owner.registry.known_device(U) is None
            if other_endpoint:
                assert owner.hub.get(D).link is opened[0] and not opened[0].closed
            else:
                assert owner.registry.claim("device:" + D) is None
            lock = EndpointLock(U)
            try:
                lock.acquire()
            finally:
                lock.close()
            response = await clients[1].post("/v2/project/takeovers", json={"endpoint": U})
            assert response.status == 200, await response.text()
            assert (await response.json())["device"]["device_id"] == B
            assert owner.registry.claim(U)["generation"] > generation
    asyncio.run(scenario())


@pytest.mark.parametrize("selected", [D, B])
def test_explicit_identity_is_checked_without_disturbing_previous_device(tmp_path, selected):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, _):
            response = await clients[1].post("/v2/project/acquire", json={"device_id": selected, "endpoint": U})
            assert response.status == (409 if selected == D else 200), await response.text()
            if selected == B:
                assert (await response.json())["device"]["device_id"] == B
            assert projects[0].hub.get(D).link is opened[0] and not opened[0].closed
    asyncio.run(scenario())


def test_preparation_rechecks_usb_before_detaching_any_old_board_link(tmp_path):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, _, opened, state):
            owner, receiver, _ = projects
            transfer = str(uuid.uuid4())
            with pytest.raises(OwnershipConflict, match="USB device changed"):
                await owner.prepare({"device_id": D, "target_session_id": receiver.registry.session_id,
                                     "transfer_id": transfer, "preferred_endpoint": {"resource": U, "metadata": OLD}})
            with pytest.raises(KeyError):
                owner.registry.transfer(transfer)
            assert owner.registry.claim(U) is None
            assert not opened[0].closed and not state["links"]
    asyncio.run(scenario())


@pytest.mark.parametrize("descriptor_changed", [True, False])
def test_failed_acceptance_is_prompt_reserved_and_resumable(tmp_path, descriptor_changed):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, _, state):
            owner, receiver, contender = projects
            state["metadata"] = OLD
            transfer = str(uuid.uuid4())
            await owner.prepare({"device_id": D, "target_session_id": receiver.registry.session_id,
                                 "transfer_id": transfer, "preferred_endpoint": {"resource": U, "metadata": OLD}})
            state["metadata"] = NEW if descriptor_changed else OLD
            path = "/v2/project/takeovers/" + transfer + "/resume"
            response = await asyncio.wait_for(clients[1].post(path, json={}), 3)
            assert response.status == 409, await response.text()
            assert "reservation retained" in (await response.json())["error"]["message"]
            assert receiver.registry.transfer(transfer)["state"] == ("offered" if descriptor_changed else "accepting")
            assert not receiver.hub.list_devices()
            assert all(link.closed for link in state["links"])
            with pytest.raises(OwnershipConflict):
                contender.registry.acquire(U, NEW)
            # Correct the physical selection and resume the same reservation.
            state.update(metadata=OLD, identity=D)
            response = await asyncio.wait_for(clients[1].post(path, json={}), 3)
            assert response.status == 200, await response.text()
            assert (await response.json())["takeover"]["state"] == "completed"
            assert receiver.hub.get(D).link.endpoint == U
    asyncio.run(scenario())


def test_owner_without_refresh_capability_is_not_handed_the_wrong_device(tmp_path):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, state):
            snapshot = projects[0].snapshot

            def legacy(**kwargs):
                result = snapshot(**kwargs)
                result["capabilities"].remove(USB_REFRESH_CAPABILITY)
                return result

            with patch.object(projects[0], "snapshot", side_effect=legacy):
                response = await clients[1].post("/v2/project/takeovers", json={"endpoint": U})
            assert response.status == 409
            assert not opened[0].closed and not state["links"]
            assert projects[0].registry.claim(U)["state"] == "owned"
    asyncio.run(scenario())


def test_replacement_descriptors_do_not_admit_a_device_without_hello(tmp_path):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, _):
            with patch.object(SerialLink, "open", side_effect=ConnectionError("device not ready")):
                response = await asyncio.wait_for(clients[1].post("/v2/project/takeovers", json={"endpoint": U}), 3)
            assert response.status == 400, await response.text()
            assert projects[1].registry.claim(U) is None
            assert projects[1].registry.claim("device:" + B) is None
            assert projects[1].registry.known_device(U) is None
            assert not projects[1].hub.list_devices()
            assert not opened[0].closed
    asyncio.run(scenario())


def test_repeated_peer_refresh_cannot_close_the_new_owners_link(tmp_path):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, clients, opened, state):
            body = {"source_session_id": "owner", "endpoint": U,
                    "generation": projects[0].registry.claim(U)["generation"]}
            path = "/v2/project/handoff/refresh-usb"
            for _ in range(2):
                response = await clients[0].post(path, json=body)
                assert response.status == 200, await response.text()
                assert (await response.json())["changed"]
            response = await clients[1].post("/v2/project/acquire", json={"endpoint": U})
            assert response.status == 200, await response.text()
            response = await clients[0].post(path, json=body)
            assert response.status == 409
            assert not state["links"][-1].closed and not opened[0].closed
            assert projects[1].registry.claim(U)["device_id"] == B
    asyncio.run(scenario())


def test_refresh_cannot_delete_a_new_generation_or_a_transfer(tmp_path):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, _, _, _):
            owner, receiver, _ = projects
            generation = owner.registry.claim(U)["generation"]
            with pytest.raises(OwnershipConflict):
                owner.registry.forget_replaced_usb(U, NEW, generation=generation - 1)
            assert owner.registry.claim(U)["device_id"] == D
            transfer = str(uuid.uuid4())
            owner.registry.prepare(D, receiver.registry.session_id, transfer)
            with pytest.raises(OwnershipConflict):
                owner.registry.forget_replaced_usb(U, NEW, generation=generation)
            assert owner.registry.claim(U)["state"] == "preparing"
    asyncio.run(scenario())


@pytest.mark.parametrize("serial", [None, "", OLD["serial_number"]])
def test_missing_serial_or_firmware_mode_change_does_not_discard_identity(tmp_path, serial):
    async def scenario():
        async with replaced_usb(tmp_path) as (projects, _, _, state):
            owner = projects[0]
            state["metadata"] = {**OLD, "serial_number": serial, "pid": 0x4003, "product": "New firmware"}
            assert not await owner.hub.refresh_owned_usb(U)
            assert owner.registry.claim(U)["device_id"] == D
            assert owner.registry.known_device(U) == D
    asyncio.run(scenario())
