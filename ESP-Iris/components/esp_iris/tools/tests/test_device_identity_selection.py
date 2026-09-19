"""Device selection must verify HELLO and clean up failed admission."""
import asyncio
from unittest.mock import patch

from test_single_device_selection import D, U, gateway, usb

OTHER = "ffeeddccbbaa99887766554433221100"


def test_device_id_alone_probes_unknown_usb_and_releases_wrong_identity(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            async def handshake(endpoint, metadata, **kwargs):
                actual = OTHER if endpoint == U else D
                g.registry.bind(endpoint, actual)
                g.live.append({"device_id": actual, "endpoint": endpoint, "boot_id": 7})
            g.connect.side_effect = handshake
            with patch("iris_gateway.device_selection.discover_iris_usb_devices", return_value=[usb(), usb("1-3")]):
                response = await g.client.post("/v1/project/acquire", json={"device_id": D})
                assert response.status == 200, await response.text()
                assert (await response.json())["device"]["endpoint"] == "usb:location=1-3"
                assert g.registry.claim(U) is None
                assert g.registry.known_endpoints(OTHER) == []
                assert len(g.registry.known_endpoints(D)) == 1
                assert g.connect.await_count == 2
    asyncio.run(scenario())


def test_device_id_tries_multiple_advertised_endpoints_without_write_replay(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            endpoints = ["tcp:host:1001", "tcp:host:1002"]
            for endpoint in endpoints:
                g.hub._candidates[endpoint] = {"endpoint": endpoint, "advertised_device_id": D}
            original = g.connect.side_effect
            async def handshake(endpoint, metadata, **kwargs):
                if endpoint == endpoints[0]:
                    raise ConnectionError("offline")
                await original(endpoint, metadata, **kwargs)
            g.connect.side_effect = handshake
            with patch("iris_gateway.device_selection.discover_iris_usb_devices", return_value=[]):
                response = await g.client.post("/v1/project/acquire", json={"device_id": D})
                assert response.status == 200
                assert g.registry.claim(endpoints[0]) is None
                assert g.registry.claim(endpoints[1])["device_id"] == D
                assert g.connect.await_count == 2
    asyncio.run(scenario())


def test_explicit_endpoint_mismatch_does_not_try_other_candidates(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            endpoint = "tcp:host:1001"
            g.hub._candidates[endpoint] = {"endpoint": endpoint}
            with patch("iris_gateway.device_selection.discover_iris_usb_devices") as discover:
                response = await g.client.post("/v1/project/acquire", json={"device_id": OTHER, "endpoint": endpoint})
                assert response.status == 400
                assert "HELLO identity" in str(await response.json())
                g.connect.assert_awaited_once()
                discover.assert_not_called()
                assert not g.registry.claims()
                assert not g.registry.known_endpoints(D)
    asyncio.run(scenario())


def test_failed_probe_preserves_existing_device_reservation(tmp_path):
    async def scenario():
        async with gateway(tmp_path) as g:
            existing, attempt = "tcp:host:1000", "tcp:host:1001"
            g.registry.acquire(existing, {})
            g.registry.bind(existing, D)
            g.connect.side_effect = ConnectionError("offline")
            response = await g.client.post("/v1/project/acquire", json={"device_id": D, "endpoint": attempt})
            assert response.status == 400
            assert g.registry.claim(existing)["device_id"] == D
            assert g.registry.claim("device:" + D)["owner"] == "a"
            assert g.registry.claim(attempt) is None
    asyncio.run(scenario())


def test_foreign_device_identity_is_never_probed(tmp_path):
    async def scenario():
        async with gateway(tmp_path, "a") as a, gateway(tmp_path, "b") as b:
            b.registry.acquire(U, {})
            b.registry.bind(U, D)
            with patch("iris_gateway.device_selection.discover_iris_usb_devices") as discover:
                response = await a.client.post("/v1/project/acquire", json={"device_id": D})
                assert response.status == 409
                discover.assert_not_called()
                a.connect.assert_not_awaited()
    asyncio.run(scenario())


def test_failed_real_hello_closes_link_supervisor_and_physical_lock(tmp_path):
    from test_hub import SupervisorLink

    from iris_gateway.link import TcpLink

    async def scenario():
        async with gateway(tmp_path, mock_handshake=False) as g:
            endpoint = "tcp:127.0.0.1:29872"
            links = []
            async def open_link(host, port):
                link = SupervisorLink(len(links) + 1, endpoint=endpoint)
                links.append(link)
                return link
            with patch.object(TcpLink, "open", side_effect=open_link):
                response = await g.client.post("/v1/project/acquire", json={
                    "device_id": OTHER, "endpoint": endpoint, "timeout": 1})
                assert response.status == 400, await response.text()
                assert links and all(link.closed for link in links)
                assert not g.hub._locks
                assert not g.hub._endpoint_tasks
                assert not g.registry.claims()
                assert not g.registry.known_endpoints(D)
                assert not g.hub.list_devices()
    asyncio.run(scenario())
