from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import ClientSession, web
from test_hub import SupervisorLink
from test_usb_ownership import until

from iris_gateway.cli import _web, build_parser
from iris_gateway.discovery import discover_iris_usb_devices
from iris_gateway.hub import IrisHub
from iris_gateway.link import SerialLink
from iris_gateway.store import GatewayStore


@pytest.fixture
def ports(tmp_path, monkeypatch):
    monkeypatch.setattr("iris_gateway.link.tempfile.gettempdir", lambda: str(tmp_path))
    current = []
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: list(current))
    return current


def board(path="/dev/review-usb", **changes):
    values = {"device": path, "location": "review:1.0", "serial_number": "board-a",
              "vid": 0x303A, "pid": 0x4002, "product": "ESP-Iris"}
    values.update(changes)
    return SimpleNamespace(**values)


async def open_board(path, **kwargs):
    return SupervisorLink(1, endpoint=kwargs["endpoint"])


def test_explicit_offline_port_connects_after_arrival(ports):
    async def scenario():
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        try:
            with patch.object(SerialLink, "open", side_effect=open_board) as opened:
                await hub.add_usb("/dev/review-usb")
                assert not hub.list_devices()
                opened.assert_not_called()
                with pytest.raises(LookupError, match="not yet bound"):
                    await hub.quiesce_endpoint(hub.list_endpoints()[0]["endpoint"])
                assert not hub._locks
                ports.append(board())
                await until(lambda: bool(hub.list_devices()))
                assert opened.call_count == 1
                assert len(hub.list_endpoints()) == 1
        finally:
            await hub.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("vid,pid,product", [
    (0x1234, 0x5678, "Custom Product"),
    (0x303A, 0x5678, "Custom Product"),
])
def test_explicit_custom_descriptors_can_handshake(ports, vid, pid, product):
    async def scenario():
        ports.append(board(vid=vid, pid=pid, product=product))
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        try:
            with patch.object(SerialLink, "open", side_effect=open_board):
                await hub.add_usb(ports[0].device)
                await until(lambda: bool(hub.list_devices()))
        finally:
            await hub.close()
    asyncio.run(scenario())


def test_offline_legacy_lease_can_be_cancelled_without_opening(ports):
    async def scenario():
        hub = IrisHub("A")
        endpoint = "usb:/dev/review-old"
        try:
            with patch.object(SerialLink, "open") as opened:
                hub.reserve_maintenance_endpoint({"endpoint": endpoint,
                                                  "path": "/dev/review-old"})
                await hub.resume_maintenance_endpoint(endpoint, restore_only=True)
                opened.assert_not_called()
                assert not hub.list_endpoints()
        finally:
            await hub.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("legacy", [False, True])
def test_web_health_and_abort_work_with_offline_usb(tmp_path, ports, legacy):
    async def scenario():
        state = tmp_path / "state"
        token = "review-token"
        if legacy:
            from iris_gateway.gateway import GatewayService
            store = GatewayStore(state)
            store.create_maintenance_lease({
                "lease_id": "offline", "device_id": "board-a",
                "token_hash": GatewayService._lease_token_hash(token),
                "purpose": "recovery", "state": "expired_quarantined",
                "endpoint": {"endpoint": "usb:/dev/review-old",
                             "path": "/dev/review-old"},
                "actor_type": "local", "actor_name": "review",
                "created_ns": 1, "expires_ns": 2,
            })
            store.close()
        argv = ["web", "--state-dir", str(state), "--port", "0",
                "--no-discover-usb", "--no-discover-mdns"]
        if not legacy:
            argv += ["--usb", "/dev/review-offline"]
        started = asyncio.Event()
        origin = []
        stops = []
        original_start = web.TCPSite.start

        async def start(site):
            await original_start(site)
            origin.append("http://127.0.0.1:" + str(
                site._server.sockets[0].getsockname()[1]))
            started.set()

        loop = asyncio.get_running_loop()
        with patch.object(web.TCPSite, "start", start), patch.object(
            loop, "add_signal_handler", side_effect=lambda sig, stop: stops.append(stop)
        ), patch.object(SerialLink, "open") as opened:
            task = asyncio.create_task(_web(build_parser().parse_args(argv)))
            ready = asyncio.create_task(started.wait())
            try:
                done, _ = await asyncio.wait((task, ready), timeout=3,
                                            return_when=asyncio.FIRST_COMPLETED)
                if task in done:
                    await task
                assert ready in done
                async with ClientSession() as client:
                    async with client.get(origin[0] + "/v1/health") as response:
                        assert response.status == 200
                    if legacy:
                        async with client.get(origin[0] + "/v1/endpoints") as response:
                            endpoints = (await response.json())["endpoints"]
                            assert endpoints[0]["state"] == "maintenance_unresolved"
                        # A failed completion must not discard the quarantine;
                        # the original token must still be able to cancel it.
                        async with client.post(
                            origin[0] + "/v1/maintenance-leases/offline/complete",
                            headers={"X-Maintenance-Token": token}, json={},
                        ) as response:
                            assert response.status == 409
                        async with client.get(
                            origin[0] + "/v1/maintenance-leases/offline"
                        ) as response:
                            assert (await response.json())["lease"]["state"] == "expired_quarantined"
                        async with client.post(
                            origin[0] + "/v1/maintenance-leases/offline/abort",
                            headers={"X-Maintenance-Token": token}, json={},
                        ) as response:
                            assert response.status == 200, await response.text()
                            assert (await response.json())["lease"]["state"] == "aborted"
                opened.assert_not_called()
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)
                if stops:
                    stops[0]()
                elif not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_pending_alias_and_discovery_share_one_supervisor(tmp_path, ports):
    async def scenario():
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        alias = tmp_path / "by-id"
        try:
            with patch.object(SerialLink, "open", side_effect=open_board) as opened:
                await hub.add_usb(str(alias))
                current = board(path=str(tmp_path / "ttyACM0"))
                alias.symlink_to(current.device)
                ports.append(current)
                await hub.start_usb_discovery(0.005)
                await until(lambda: bool(hub.list_devices()) and not hub._pending_usb)
                assert opened.call_count == 1
                assert len(hub.list_endpoints()) == 1
                assert hub.list_endpoints()[0]["usb_selection"] == "explicit"
        finally:
            await hub.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("jtag", [False, True])
def test_discovery_cannot_replace_pending_explicit_policy(ports, jtag):
    async def scenario():
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        try:
            with patch.object(SerialLink, "open", side_effect=open_board):
                await hub.add_usb("/dev/review-usb", usb_serial_jtag=jtag)
                await hub.add_usb("/dev/review-usb", discovered=True)
                ports.append(board(
                    vid=0x303A if jtag else 0x1234,
                    pid=0x1001 if jtag else 0x5678,
                    product="Custom",
                ))
                await until(lambda: bool(hub.list_devices()))
                assert hub.list_endpoints()[0]["usb_selection"] == "explicit"
        finally:
            await hub.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("pid,allow_jtag", [(0x1001, False), (0x0020, False), (0x0020, True)])
def test_explicit_selection_still_rejects_unapproved_download_interfaces(ports, pid, allow_jtag):
    async def scenario():
        ports.append(board(pid=pid, product="ROM or JTAG"))
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        try:
            with patch.object(SerialLink, "open") as opened:
                await hub.add_usb(ports[0].device, usb_serial_jtag=allow_jtag)
                await until(lambda: hub.list_endpoints()[0]["attempt"] >= 2)
                opened.assert_not_called()
        finally:
            await hub.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("explicit", [False, True])
def test_discovery_refresh_and_maintenance_preserve_connection_policy(ports, explicit):
    async def scenario():
        current = board()
        ports.append(current)
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        restored = IrisHub("B", reconnect_min_seconds=0.005)
        try:
            with patch.object(SerialLink, "open", side_effect=open_board) as opened:
                await hub.add_usb(current.device, discovered=not explicit)
                await until(lambda: bool(hub.list_devices()))
                await hub.add_usb(current.device, discovered=True)
                lease = await hub.quiesce_endpoint(current.device)
                await hub.close()
                current.vid, current.pid, current.product = 0x1234, 0x5678, "Custom"
                assert discover_iris_usb_devices() == []
                restored.reserve_maintenance_endpoint(lease)
                await restored.resume_maintenance_endpoint(lease["endpoint"], restore_only=True)
                if explicit:
                    await until(lambda: bool(restored.list_devices()))
                    assert opened.call_count == 2
                else:
                    await until(lambda: restored.list_endpoints()[0]["attempt"] >= 2)
                    assert opened.call_count == 1
        finally:
            await restored.close()
            await hub.close()
    asyncio.run(scenario())


def test_serial_jtag_opt_in_survives_discovery_refresh(ports):
    async def scenario():
        current = board()
        ports.append(current)
        hub = IrisHub("A", reconnect_min_seconds=0.005)
        links = []

        async def open_link(path, **kwargs):
            link = await open_board(path, **kwargs)
            links.append(link)
            return link

        try:
            with patch.object(SerialLink, "open", side_effect=open_link) as opened:
                await hub.add_usb(current.device, usb_serial_jtag=True)
                await until(lambda: bool(hub.list_devices()))
                await hub.add_usb(current.device, discovered=True)
                current.pid, current.product = 0x1001, "USB JTAG/serial debug unit"
                await links[0].incoming.put(b"")
                await until(lambda: len(links) == 2)
                assert opened.call_args.kwargs["hupcl"] is False
        finally:
            await hub.close()
    asyncio.run(scenario())


def test_legacy_serial_reservation_rebinds_without_claiming_reused_tty(ports):
    async def scenario():
        owner = IrisHub("A", reconnect_min_seconds=0.005)
        other = IrisHub("B", reconnect_min_seconds=0.005)
        endpoint = "usb:serial=board-a"
        owner.reserve_maintenance_endpoint({
            "endpoint": endpoint, "path": "/dev/old", "serial_number": "board-a",
        })
        try:
            with patch.object(SerialLink, "open", side_effect=open_board) as opened:
                reused = board(path="/dev/old", serial_number="board-b", location="other:1.0")
                ports.append(reused)
                await other.add_usb(reused.device)
                await until(lambda: bool(other.list_devices()))
                ports.append(board(path="/dev/new"))
                await until(lambda: owner.list_endpoints()[0]["state"] == "maintenance_detached")
                assert owner.list_endpoints()[0]["lock_endpoint"] == "usb:location=review:1.0"
                await other.add_usb("/dev/new")
                await until(lambda: any(item["state"] == "owned_elsewhere"
                                        for item in other.list_endpoints()))
                assert opened.call_count == 1
        finally:
            await other.close()
            await owner.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["physical", "unknown_lease"])
def test_cross_process_ownership_and_crash_cleanup(tmp_path, ports, kind):
    async def scenario():
        ready = tmp_path / "owner-ready"
        code = '''
import pathlib, sys, tempfile
tempfile.tempdir = sys.argv[1]
from iris_gateway.link import EndpointLock
from iris_gateway.usb_ownership import UsbQuarantine
if sys.argv[2] == "physical":
    owner = EndpointLock("usb:location=review:1.0")
    owner.acquire()
else:
    owner = UsbQuarantine({"endpoint": "usb:/dev/offline", "path": "/dev/offline"})
pathlib.Path(sys.argv[3]).touch()
sys.stdin.read()
'''
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code, str(tmp_path), kind, str(ready),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        hub = IrisHub("B", reconnect_min_seconds=0.005, reconnect_max_seconds=0.01)
        ports.append(board())
        try:
            await until(lambda: ready.exists() or process.returncode is not None)
            assert ready.exists(), await asyncio.wait_for(process.communicate(), 2)
            with patch.object(SerialLink, "open", side_effect=open_board) as opened:
                await hub.add_usb(ports[0].device)
                await until(lambda: hub.list_endpoints()[0]["state"] == "owned_elsewhere")
                opened.assert_not_called()
                process.terminate()
                await asyncio.wait_for(process.wait(), 5)
                await until(lambda: bool(hub.list_devices()))
                assert opened.call_count == 1
                assert not list((tmp_path / "esp-iris-locks").glob("usb-quarantine-*.json"))
        finally:
            if process.returncode is None:
                process.kill()
            await asyncio.wait_for(process.communicate(), 5)
            await hub.close()
    asyncio.run(scenario())
