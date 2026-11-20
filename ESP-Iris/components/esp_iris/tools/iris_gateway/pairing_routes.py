"""Explicit local pairing; HTTP responses and audit records never contain secrets."""
from __future__ import annotations

from typing import Any

from aiohttp import web

from .http_support import request_actor, request_is_loopback


def register_pairing_routes(app: web.Application, service: Any) -> None:
    def require_local(request: web.Request) -> None:
        if not request_is_loopback(request):
            raise PermissionError("pairing management is local-only")

    async def inventory(request: web.Request) -> web.Response:
        require_local(request)
        return web.json_response({"devices": service.pairings.devices()})

    async def pair(request: web.Request) -> web.Response:
        require_local(request)
        device_id = service.resolve_device(request.match_info["device_id"])
        token = await service.device_hub.pairing_token_over_usb(device_id)
        service.pairings.remember(device_id, token)
        actor = request_actor(request)
        service.store.add_audit(actor.kind, actor.name, "device.paired", {"device_id": device_id})
        return web.json_response({"device_id": device_id, "paired": True})

    async def forget(request: web.Request) -> web.Response:
        require_local(request)
        device_id = request.match_info["paired_device_id"]
        service.pairings.forget(device_id)
        project = service.project
        if project is not None:
            for endpoint in list(project.tokens):
                if project.registry.known_device(endpoint) == device_id:
                    project.tokens.pop(endpoint)
        actor = request_actor(request)
        service.store.add_audit(actor.kind, actor.name, "device.pairing_forgotten", {"device_id": device_id})
        return web.json_response({"device_id": device_id, "paired": False})

    app.router.add_get("/v2/pairings", inventory)
    app.router.add_delete("/v2/pairings/{paired_device_id}", forget)
    app.router.add_post("/v2/devices/{device_id}/pairing", pair)
