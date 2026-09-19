"""Local project-session HTTP control and device admission."""
from __future__ import annotations

import asyncio
import collections
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from .compat import to_thread
from .discovery import iris_usb_allowed, resolve_usb_port, usb_endpoint
from .http_support import request_is_loopback
from .ownership import CAPABILITY, OwnershipConflict, OwnershipRegistry


class ProjectGateway:
    capability = CAPABILITY

    def __init__(self, registry: OwnershipRegistry, service: Any, hub: Any,
                 stop: asyncio.Event, *, pairing_token: str | None = None) -> None:
        self.registry, self.service, self.hub = registry, service, hub
        self.stop = stop
        self.pairing_token = pairing_token
        self.tokens: dict[str, str] = {}
        self.closing = False
        self.drain_requested = asyncio.Event()
        self.drain_timed_out = False
        self.active: dict[str, int] = collections.defaultdict(int)
        self.blocked: set[str] = set()
        self.control_lock = asyncio.Lock()
        self.jobs: dict[tuple[str, int], dict[str, Any]] = {}

    def observe(self, event: dict[str, Any]) -> None:
        device_id = str(event.get("device_id") or "")
        if event.get("kind") == "job":
            key = (device_id, int(event["job_id"]))
            if event.get("job_state") in {"succeeded", "failed", "cancelled"}:
                self.jobs.pop(key, None)
            else:
                self.jobs[key] = dict(event)
        elif event.get("kind") == "connection" and event.get("connection_state") == "rebooted":
            self.jobs = {key: value for key, value in self.jobs.items() if key[0] != device_id}

    def busy(self, device_id: str | None = None) -> bool:
        operations = self.service.operations
        if device_id is None:
            return bool(any(self.active.values()) or operations._pending or self.jobs
                        or self.service.store.active_maintenance_leases())
        state = operations.queue_state(device_id)
        return bool(self.active[device_id] or state["running"] or state["queued"]
                    or state["maintenance"] or any(key[0] == device_id for key in self.hub._mirror_states)
                    or any(key[0] == device_id for key in self.jobs))

    def request_stop(self) -> None:
        self.closing = True
        self.drain_requested.set()

    async def drain(self, timeout: float = 900) -> None:
        await self.drain_requested.wait()
        deadline = time.monotonic() + timeout
        while self.busy() and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        self.drain_timed_out = self.busy()
        self.stop.set()

    @web.middleware
    async def guard(self, request: web.Request, handler: Any) -> web.StreamResponse:
        if self.closing and request.path == "/v1/maintenance-endpoints/leases":
            raise OwnershipConflict("project session is draining")
        device_id = request.match_info.get("device_id")
        if not device_id:
            return await handler(request)
        device_id = self.service.resolve_device(device_id)
        if self.closing or device_id in self.blocked:
            raise OwnershipConflict("project session or device is draining")
        self.registry._require("device:" + device_id, ("owned",))
        # Passive subscriptions end with the server and must not keep its
        # owner alive. Active mirror producers still block device transfer.
        if request.method == "GET" and "/streams/" in request.path:
            return await handler(request)
        self.active[device_id] += 1
        try:
            return await handler(request)
        finally:
            self.active[device_id] -= 1

    def snapshot(self) -> dict[str, Any]:
        claims = self.registry.claims()
        return {"session": self.registry.session(self.registry.session_id),
                "capability": CAPABILITY, "closing": self.closing,
                "pairing_configured": bool(self.pairing_token),
                "busy": self.busy(), "sessions": self.registry.sessions(),
                "claims": claims, "endpoints": self.hub.list_endpoints(),
                "transfers": [self.registry.transfer(key) for key in sorted({
                    item["transfer_id"] for item in claims if item["transfer_id"]
                })]}

    async def wait_device(self, device_id: str | None, endpoint: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + min(30.0, max(0.1, timeout))
        while time.monotonic() < deadline:
            for item in self.hub.list_devices():
                if (device_id and item["device_id"] == device_id) or (
                    not device_id and item.get("endpoint") == endpoint
                ):
                    return item
            await asyncio.sleep(0.05)
        raise TimeoutError("device has not completed identity validation; ownership is retained")

    async def acquire(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.closing:
            raise OwnershipConflict("project session is draining")
        device_id = body.get("device_id")
        endpoint = body.get("endpoint")
        token = body.get("pairing_token")
        if token is not None and (not isinstance(token, str) or len(bytes.fromhex(token)) != 32):
            raise ValueError("pairing token must contain 32 bytes")
        if not device_id and not endpoint:
            raise ValueError("select --device-id or --endpoint; discovery never acquires devices")
        if device_id:
            claim = self.registry.claim("device:" + str(device_id))
            if claim:
                self.registry._require("device:" + str(device_id), ("owned",))
                connected = next((item for item in self.hub.list_devices() if item["device_id"] == device_id), None)
                if connected is not None:
                    return connected
        candidates = self.hub.list_endpoints()
        if endpoint:
            candidates = [item for item in candidates if item["endpoint"] == endpoint or item.get("path") == endpoint]
            if not candidates and str(endpoint).startswith("tcp:"):
                host, port = str(endpoint)[4:].rsplit(":", 1)
                if not host or not 1 <= int(port) <= 65535:
                    raise ValueError("invalid TCP endpoint")
                candidates = [{"endpoint": endpoint}]
            elif not candidates:
                metadata = await to_thread(resolve_usb_port, str(endpoint))
                if not iris_usb_allowed(metadata, explicit=True):
                    raise ValueError("endpoint is reserved for the Recovery maintenance workflow")
                candidates = [{"endpoint": usb_endpoint(metadata), **metadata}]
        else:
            candidates = [item for item in candidates if item.get("advertised_device_id") == device_id
                          or (item.get("ownership") or {}).get("device_id") == device_id]
            if not candidates:
                candidates = self.registry.known_endpoints(str(device_id))
        if len(candidates) != 1:
            raise ValueError("select one discovered endpoint; use session status to inspect candidates")
        metadata = {key: value for key, value in candidates[0].items() if key != "ownership"}
        endpoint = str(metadata["endpoint"])
        self.registry.acquire(endpoint, metadata)
        if device_id:
            self.registry.bind(endpoint, str(device_id), verified=False)
        if token is not None:
            self.tokens[endpoint] = token
        await self.hub.connect_owned(endpoint, metadata, pairing_token=self.tokens.get(endpoint, self.pairing_token))
        return await self.wait_device(str(device_id) if device_id else None, endpoint, float(body.get("timeout", 10)))

    async def prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        device_id, target = str(body["device_id"]), str(body["target_session_id"])
        transfer_id = str(body.get("transfer_id") or uuid.uuid4())
        try:
            existing = self.registry.transfer(transfer_id)
        except KeyError:
            existing = None
        if existing:
            if (existing["device_id"], existing["source"], existing["target"]) != (
                device_id, self.registry.session_id, target,
            ):
                raise OwnershipConflict("transfer ID already describes a different request")
            if existing["state"] != "preparing":
                return existing
        if self.closing or self.busy(device_id):
            raise OwnershipConflict("device is busy; retry after the active operation finishes")
        self.blocked.add(device_id)
        try:
            self.registry.prepare(device_id, target, transfer_id)
            await self.hub.detach_owned(device_id)
            result = self.registry.offer(transfer_id)
            self.audit(result)
            return result
        finally:
            self.blocked.discard(device_id)

    def audit(self, transfer: dict[str, Any]) -> None:
        self.service.store.add_audit("project", self.registry.session_id,
                                     "device.transfer." + transfer["state"], transfer)

    async def accept(self, transfer_id: str) -> dict[str, Any]:
        if self.closing:
            raise OwnershipConflict("project session is draining")
        proposed = self.registry.transfer(transfer_id)
        if any(item["metadata"].get("pairing") == "hmac" for item in proposed["metadata"]["endpoints"]) and not self.pairing_token:
            raise OwnershipConflict("target requires its own pairing token before acceptance")
        result = self.registry.accept(transfer_id)
        if result["state"] == "completed":
            return result
        endpoints = result["metadata"]["endpoints"]
        # A single verified transport is sufficient. Credentials stay local.
        endpoint = endpoints[0]
        await self.hub.connect_owned(endpoint["resource"], endpoint["metadata"], pairing_token=self.pairing_token)
        await self.wait_device(result["device_id"], endpoint["resource"], 15)
        result = self.registry.complete(transfer_id, result["device_id"])
        self.audit(result)
        return result

    async def transfer_to(self, body: dict[str, Any]) -> dict[str, Any]:
        target_id = str(body["target_session_id"])
        if body.get("transfer_id"):
            try:
                previous = self.registry.transfer(str(body["transfer_id"]))
            except KeyError:
                previous = None
            if previous:
                if (previous["source"], previous["target"], previous["device_id"]) != (
                    self.registry.session_id, target_id, body["device_id"],
                ):
                    raise OwnershipConflict("transfer ID already describes a different request")
                if previous["state"] == "completed":
                    return previous
                if previous["state"] == "aborted":
                    raise OwnershipConflict("transfer was aborted; create a new transfer request")
        target = self.registry.session(target_id)
        address = urlsplit(target["url"])
        if not target["alive"] or address.scheme != "http" or address.hostname != "127.0.0.1":
            raise OwnershipConflict("target must be a live local project session")
        async with ClientSession(timeout=ClientTimeout(total=30)) as client:
            async with client.get(target["url"] + "/v1/project") as response:
                state = await response.json()
                if (response.status != 200 or state.get("session", {}).get("session_id") != target_id
                        or state.get("capability") != CAPABILITY or state.get("closing")):
                    raise OwnershipConflict("target is unavailable or its identity changed")
            # Missing credentials fail before disrupting the source.
            claims = [item for item in self.registry.claims() if item["device_id"] == body["device_id"]]
            if any(item["metadata"].get("pairing") == "hmac" for item in claims) and not state.get("pairing_configured"):
                raise OwnershipConflict("configure the target's pairing token first")
            transfer = await self.prepare(body)
            async with client.post(target["url"] + "/v1/project/accept", json={"transfer_id": transfer["transfer_id"]}) as response:
                result = await response.json()
                if response.status != 200:
                    raise OwnershipConflict(f"Transfer {transfer['transfer_id']} remains reserved; query its status and retry acceptance: {result}")
                return result["transfer"]

    def register_routes(self, app: web.Application) -> None:
        async def handle(request: web.Request) -> web.Response:
            if not request_is_loopback(request):
                raise PermissionError("project session control is local-only")
            action = request.match_info.get("action", "status")
            if request.method == "GET":
                if action == "status":
                    return web.json_response(self.snapshot())
                return web.json_response({"transfer": self.registry.transfer(action)})
            body = await request.json()
            async with self.control_lock:
                if action == "acquire":
                    return web.json_response({"device": await self.acquire(body)})
                if action == "prepare":
                    return web.json_response({"transfer": await self.prepare(body)})
                if action == "transfer":
                    body.setdefault("transfer_id", str(uuid.uuid4()))
                    try:
                        return web.json_response({"transfer": await self.transfer_to(body)})
                    except (ClientError, asyncio.TimeoutError) as error:
                        raise OwnershipConflict(
                            f"Transfer {body['transfer_id']}: peer response unavailable; query its durable status before retrying"
                        ) from error
                if action == "accept":
                    return web.json_response({"transfer": await self.accept(str(body["transfer_id"]))})
                if action == "abort":
                    transfer_id = str(body["transfer_id"])
                    before = self.registry.transfer(transfer_id)
                    if before["source"] != self.registry.session_id:
                        raise OwnershipConflict("only the source can abort")
                    await self.hub.detach_owned(before["device_id"])
                    result = self.registry.abort(transfer_id)
                    self.audit(result)
                    return web.json_response({"transfer": result})
                if action == "release":
                    resource = str(body.get("endpoint") or ("device:" + str(body["device_id"])))
                    claim = self.registry._require(resource, ("owned",))
                    device_id = claim["device_id"]
                    if self.busy(device_id):
                        raise OwnershipConflict("device is busy")
                    self.blocked.add(device_id or resource)
                    try:
                        if device_id:
                            await self.hub.detach_owned(device_id)
                        else:
                            await self.hub._remove_endpoint(resource)
                        self.registry.release(resource)
                    finally:
                        self.blocked.discard(device_id or resource)
                    return web.json_response({"released": resource})
                if action == "reconcile":
                    resource = str(body.get("endpoint") or ("device:" + str(body["device_id"])))
                    self.registry.reconcile_orphan(resource)
                    return web.json_response({"reconciled": resource})
                if action == "reconcile-transfer":
                    result = self.registry.reconcile_transfer(str(body["transfer_id"]))
                    self.audit(result)
                    return web.json_response({"transfer": result})
                raise ValueError("unknown project action")

        app.router.add_get("/v1/project", handle)
        app.router.add_get("/v1/project/transfers/{action}", handle)
        app.router.add_post("/v1/project/{action}", handle)
