"""Local ROM work participates in the normal operation queue and history."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import uuid
from typing import Any

from aiohttp import web

from .device_activity import stop_session_work
from .firmware import inspect_firmware_image
from .host_worker import active_workers, consume_request
from .http_support import json_body, request_actor, request_is_loopback
from .operations import OperationOutcomeUnknown
from .reconciliation import save_reconciliation


def _target_identity(device_id: str | None, mac: str | None) -> str | None:
    if device_id:
        return device_id
    if mac and re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        return (b"ESP-IRIS\x01\x00" + bytes.fromhex(mac.replace(":", ""))).hex()
    return None


class HostOperations:
    def __init__(self, service: Any) -> None:
        self.service = service

    async def submit(self, request_id: str, actor: Any) -> dict:
        service = self.service
        existing = service.store.operation(request_id)
        if existing is not None:
            return existing
        spec = consume_request(request_id)
        action = spec.get("action")
        if action not in {"host.recovery", "host.probe", "host.flash"}:
            raise ValueError("unsupported host operation")
        commands = spec.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ValueError("host operation requires foreground commands")
        for command in commands:
            if not isinstance(command, dict) or not command.get("argv"):
                raise ValueError("host command requires argv")
            if not all(isinstance(part, str) and part for part in command["argv"]):
                raise ValueError("host argv must contain nonempty strings")
        timeout = float(spec.get("timeout", 60))
        if not 0 < timeout <= 3600:
            raise ValueError("timeout must be between zero and 3600 seconds")
        hub = service.device_hub
        device_id = spec.get("device_id")
        if action == "host.flash" and spec.get("endpoint"):
            identifier = str(spec["endpoint"])
        elif device_id:
            device_id = service.resolve_device(device_id)
            target = hub.get(device_id)
            identifier = target.link.endpoint
        else:
            identifier = str(spec.get("endpoint") or "")
            if not identifier:
                raise ValueError("device_id or endpoint is required")
        primary = hub.host_endpoint(identifier)
        if action == "host.flash":
            if device_id and primary.get("device_id") not in (None, device_id):
                raise ValueError("flash endpoint belongs to a different device")
            if spec.get("write_endpoint"):
                raise ValueError("native flash uses one UART or USB Serial/JTAG endpoint")
            hub.configure_host_console(primary["endpoint"], baudrate=spec.get("baudrate", 115200), validate_only=True)
            if spec.get("flash_target") not in {"flash", "app-flash"}:
                raise ValueError("invalid native flash target")
            if not 0 <= float(spec.get("reconnect_timeout", 10)) <= 60:
                raise ValueError("invalid reconnect timeout")
        endpoints = [primary]
        if spec.get("write_endpoint"):
            writer = hub.host_endpoint(spec["write_endpoint"])
            if writer["endpoint"] == primary["endpoint"]:
                raise ValueError("an independent write endpoint must differ from the managed endpoint")
            if writer["endpoint"] != primary["endpoint"]:
                if writer.get("device_id") and writer["device_id"] != device_id:
                    raise ValueError("write endpoint belongs to a different device")
                endpoints.append(writer)
        else:
            writer = primary
        device_id = device_id or primary.get("device_id")
        if action == "host.flash":
            spec["expected_device_id"] = device_id
        if action == "host.recovery":
            mac = spec.get("expected_hardware_mac")
            if not mac and not device_id:
                serial = str(writer.get("serial_number") or "").lower()
                if re.fullmatch(r"(?:[0-9a-f]{12}|[0-9a-f]{2}(?::[0-9a-f]{2}){5})", serial):
                    raw = serial.replace(":", "")
                    mac = ":".join(raw[index:index + 2] for index in range(0, 12, 2))
            spec["expected_hardware_mac"] = str(mac).lower() if mac else None
            if mac and not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", spec["expected_hardware_mac"]):
                raise ValueError("expected_hardware_mac must be a factory MAC in colon-separated form")
            spec["expected_device_id"] = _target_identity(device_id, spec["expected_hardware_mac"])
            if not spec["expected_device_id"]:
                raise ValueError("ROM recovery requires a verified Device ID or factory hardware MAC")
            if spec.get("image_path"):
                spec["expected_image"] = inspect_firmware_image(pathlib.Path(spec["image_path"]).read_bytes()).as_dict()
        # ROM entry re-enumerates the whole USB device. Detach every live USB
        # interface with the same verified identity, including the data CDC.
        if device_id:
            selected = {item["endpoint"] for item in endpoints}
            for peer in hub.list_endpoints():
                endpoint = str(peer["endpoint"])
                if (endpoint.startswith("usb:") and endpoint not in selected
                        and peer.get("state") == "ready" and peer.get("device_id") == device_id):
                    endpoints.append(hub.host_endpoint(endpoint))
                    selected.add(endpoint)
        resources = sorted({str(item.get("device_id") or "endpoint::" + item["endpoint"])
                            for item in endpoints} | {item["endpoint"] for item in endpoints})
        if spec.get("expected_device_id"):
            resources = sorted(set(resources) | {spec["expected_device_id"]})
        key = device_id or "endpoint::" + primary["endpoint"]
        if service.project is not None and (
            service.project.closing or any(item in service.project.blocked for item in resources)
        ):
            raise RuntimeError("device or project is draining")
        params = {"endpoints": endpoints, "expected_version": spec.get("expected_version"),
                  "expected_hardware_mac": spec.get("expected_hardware_mac"),
                  "expected_device_id": spec.get("expected_device_id"),
                  "expected_image": spec.get("expected_image"),
                  "flash_target": spec.get("flash_target"), "images": spec.get("images"),
                  "request_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()}
        operation, _ = await service.operations.submit(
            key, actor, action, params,
            lambda: self.run(request_id, spec, device_id, endpoints, writer, resources, timeout),
            operation_id=request_id, exclusive_resources=tuple(resources),
        )
        return operation

    async def run(self, operation_id: str, spec: dict, device_id: str | None,
                  endpoints: list[dict], writer: dict, resources: list[str], timeout: float) -> dict:
        service, hub = self.service, self.service.device_hub
        directory = service.store.artifacts_dir / "host-operations" / operation_id
        directory.mkdir(parents=True, exist_ok=True)
        evidence = {}
        await service.operations.progress(operation_id, stage="preserving_evidence", progress_permille=0)
        if device_id and spec["action"] == "host.flash":
            # A crashed/unresponsive application must not prevent hardware ROM
            # entry. Snapshot cached identity only; the native tool owns reset.
            before = hub.device_snapshot(device_id)
            if before:
                evidence["device_before"] = before
                service.store.remember_device(before)
        elif device_id:
            await stop_session_work(service, device_id, timeout)
            before = await hub.status(device_id)
            if before.get("device_id") != device_id or not before.get("boot_id"):
                raise RuntimeError("host operation requires verified device and boot identity")
            # Persist the verified identity before detaching for the writer.
            # Inventory queries are read-only and cannot be relied on to have
            # cached a just-connected device already.
            service.store.remember_device(before)
            evidence["device_before"] = before
            evidence["crash_index"] = await hub.crash_report(device_id)
            evidence["coredump"] = await service.preserve_coredump(device_id)
        (directory / "before.json").write_text(json.dumps(evidence), encoding="utf-8")
        detached = []
        process = None
        writer_finished = False
        try:
            for endpoint in endpoints:
                detached.append(await hub.detach_for_host(endpoint["endpoint"]))
                if service.project is not None and spec.get("expected_device_id"):
                    service.project.registry.bind(endpoint["endpoint"], spec["expected_device_id"], verified=False)
            if spec["action"] == "host.flash":
                # Change console configuration only after admission and detach,
                # never while another operation still owns this live endpoint.
                hub.configure_host_console(endpoints[0]["endpoint"], baudrate=spec.get("baudrate", 115200))
            for endpoint in detached:
                hub.yield_host_lock(endpoint["endpoint"])
            await service.operations.progress(operation_id, stage="transferring", progress_permille=100)
            worker_spec = {
                "operation_id": operation_id, "resources": resources, "endpoints": endpoints,
                "locks": [item.get("lock_endpoint") or item["endpoint"] for item in detached],
                "write_endpoint": writer.get("lock_endpoint") or writer["endpoint"],
                "commands": spec["commands"], "log_path": str(directory / "output.log"),
                "result_path": str(directory / "result.json"),
            }
            options = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "iris_gateway.host_worker",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(pathlib.Path(__file__).resolve().parent.parent), **options,
            )
            assert process.stdin is not None
            process.stdin.write(json.dumps(worker_spec).encode())
            await process.stdin.drain()
            process.stdin.close()
            # Cancellation of this coroutine never signals the independent
            # worker. Its physical locks protect any still-running writer.
            if spec["action"] == "host.flash":
                await self.wait_writer(process, operation_id, directory / "output.log")
            else:
                await process.wait()
            writer_finished = True
            result_path = directory / "result.json"
            if not result_path.is_file():
                raise OperationOutcomeUnknown("host worker exited without a result; inspect its raw log")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("returncode"):
                if spec["action"] == "host.flash":
                    await service.operations.progress(operation_id, stage="transferring", progress_permille=900,
                                                      native_returncode=result["returncode"],
                                                      log_path=str(directory / "output.log"))
                raise RuntimeError(result.get("error", "host operation failed"))
            if result.get("returncode") != 0:
                raise OperationOutcomeUnknown("host worker did not record a completed write")
            if spec["action"] == "host.recovery":
                evidence["write_completed"] = True
                await service.operations.progress(operation_id, stage="verifying", progress_permille=900,
                                                  write_completed=True, log_path=str(directory / "output.log"))
                await hub.resume_after_host(endpoints[0]["endpoint"], connect=True)
                verification = await self.verify(spec["expected_device_id"],
                                                 evidence.get("device_before", {}), spec, timeout)
                evidence["verification"] = verification
            elif spec["action"] == "host.flash":
                evidence["write_completed"] = True
                await service.operations.progress(operation_id, stage="reconnecting", progress_permille=950,
                                                  write_completed=True, log_path=str(directory / "output.log"))
                # IDF owns reset policy, including --after no_reset.
                try:
                    await hub.resume_after_host(endpoints[0]["endpoint"], connect=True)
                    evidence["connection"] = await self.observe_flash_connection(
                        endpoints[0]["endpoint"], spec, evidence.get("device_before", {}))
                except (OSError, LookupError, RuntimeError, ValueError, asyncio.TimeoutError) as error:
                    evidence["connection"] = {"state": "unavailable", "error": str(error)}
            return {"evidence": evidence, "endpoint": endpoints[0]["endpoint"], "log_path": str(directory / "output.log"),
                    "returncode": 0, "stdout": result.get("stdout", "")[-65536:]}
        except Exception as error:  # Delivery can fail after the process has started.
            delivery_uncertain = process is not None and not writer_finished
            if process is not None and not writer_finished:
                if process.stdin is not None:
                    process.stdin.close()
                await process.wait()
                writer_finished = True
            if delivery_uncertain or evidence.get("write_completed"):
                raise OperationOutcomeUnknown(
                    "ROM operation needs verification; its write was not replayed: " + str(error)
                ) from error
            raise
        finally:
            try:
                # Spawn failure is safe to unwind; a disconnected Gateway must not
                # reconnect while its independent worker is still writing.
                if process is None or writer_finished:
                    for endpoint in reversed(detached):
                        try:
                            await hub.resume_after_host(endpoint["endpoint"])
                        except (OSError, LookupError, RuntimeError, ValueError) as error:
                            if spec["action"] != "host.flash":
                                raise
                            evidence.setdefault("resume_errors", []).append(str(error))
            finally:
                (directory / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")

    async def wait_writer(self, process: Any, operation_id: str, log_path: pathlib.Path) -> None:
        """Expose bounded native output while leaving writer lifetime independent."""
        pending = asyncio.ensure_future(process.wait())
        offset = 0
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=0.2)
                if log_path.exists():
                    with log_path.open("rb") as stream:
                        stream.seek(offset)
                        data = stream.read(16384)
                        offset = stream.tell()
                    if data:
                        await self.service.operations.progress(
                            operation_id, stage="transferring", progress_permille=100, log_path=str(log_path),
                            output=data.decode("utf-8", errors="replace"), output_offset=offset)
                if done:
                    await pending
                    return
        finally:
            # Cancelling the wait task does not signal the independent process.
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def observe_flash_connection(self, endpoint: str, spec: dict, before: dict) -> dict:
        hub = self.service.device_hub
        deadline = asyncio.get_running_loop().time() + float(spec.get("reconnect_timeout", 10))
        last = {"state": "waiting", "endpoint": endpoint}
        while True:
            peers = {item.get("device_id") for item in hub.list_endpoints()
                     if item["endpoint"] == endpoint and item.get("device_id")}
            for status in hub.list_devices():
                if status["device_id"] not in peers:
                    continue
                expected = spec.get("expected_device_id")
                if expected and status["device_id"] != expected:
                    return {"state": "identity_mismatch", "status": status}
                if not status.get("boot_id") or str(status["boot_id"]) == str(before.get("boot_id")):
                    continue
                return {"state": "connected", "status": status}
            if asyncio.get_running_loop().time() >= deadline:
                return last
            await asyncio.sleep(0.05)

    async def _connect(self, device_id: str, timeout: float) -> None:
        project = self.service.project
        async with project.control_lock:
            await project.acquire({"device_id": device_id, "timeout": min(2, timeout)})

    async def verify(self, device_id: str, before: dict,
                     spec: dict, timeout: float) -> dict:
        hub = self.service.device_hub
        deadline = asyncio.get_running_loop().time() + timeout
        last_error = "target device has not reconnected"
        while asyncio.get_running_loop().time() < deadline:
            project = self.service.project
            if project is not None:
                try:
                    remaining = max(.001, deadline - asyncio.get_running_loop().time())
                    await asyncio.wait_for(self._connect(device_id, remaining), remaining)
                except (OSError, LookupError, RuntimeError, asyncio.TimeoutError, web.HTTPBadRequest) as error:
                    last_error = str(error)
                    await asyncio.sleep(.05)
                    continue
            for candidate in hub.list_devices():
                if candidate["device_id"] != device_id:
                    continue
                try:
                    status = await asyncio.wait_for(hub.status(candidate["device_id"]),
                                                    max(0.001, deadline - asyncio.get_running_loop().time()))
                except (OSError, LookupError, asyncio.TimeoutError):
                    continue
                image = spec.get("expected_image") or {}
                if (status.get("device_id") == candidate["device_id"]
                        and status.get("boot_id") not in (None, "")
                        and str(status["boot_id"]) != str(before.get("boot_id"))
                        and status.get("firmware_mode") == "recovery"
                        and "ota" in status.get("capability_names", [])
                        and (not spec.get("expected_version") or status.get("app_version") == spec["expected_version"])
                        and (not image or (status.get("project_name") == image.get("project_name")
                             and image.get("elf_sha256") and status.get("firmware_sha256") == image["elf_sha256"]))
                        and (not spec.get("expected_hardware_mac") or status.get("hardware_mac") == spec["expected_hardware_mac"])):
                    return status
                last_error = "live identity, boot, firmware or OTA readiness did not match"
            await asyncio.sleep(0.05)
        raise OperationOutcomeUnknown("ROM write finished; Vibe Mode verification is pending: " + last_error)

    async def reconcile(self, operation_id: str, actor: Any) -> dict:
        """Continue acceptance only; retain the original write and terminal record."""
        service = self.service
        operation = service.store.operation(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        flash = operation["action"] == "host.flash"
        statuses = {"outcome_unknown", "interrupted", "failed"} | ({"succeeded"} if flash else set())
        if operation["action"] not in {"host.recovery", "host.flash"} or operation["status"] not in statuses:
            raise ValueError("only completed native flash or unfinished recovery acceptance can be verified again")
        params = operation["params"]
        target = params.get("expected_device_id")
        resources = {operation["device_id"], target} | {
            item["endpoint"] for item in params.get("endpoints", [])}
        if any(resources.intersection(worker["resources"]) for worker in active_workers()):
            raise RuntimeError("a host writer still owns the target; wait for it to finish")
        record = {"reconciliation_id": str(uuid.uuid4()), "operation_id": operation_id,
                  "device_id": target or operation["device_id"], "actor": actor.as_dict(),
                  "observed_ns": time.time_ns(), "outcome": "outcome_unknown", "replayed": False,
                  "evidence": {}, "reason": "completed write or target identity evidence is missing"}
        directory = service.store.artifacts_dir / "host-operations" / operation_id
        try:
            result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            before = json.loads((directory / "before.json").read_text(encoding="utf-8")).get("device_before", {})
            if flash and result.get("returncode") == 0:
                async def inspect_flash() -> dict:
                    connection = await self.observe_flash_connection(
                        params["endpoints"][0]["endpoint"], {**params, "reconnect_timeout": 0}, before)
                    return {"write_completed": True, "connection": connection}

                _, evidence, _ = await service.operations.execute(
                    operation["device_id"], actor, "host.flash.verify", {"source_operation_id": operation_id},
                    inspect_flash, exclusive_resources=tuple(sorted(item for item in resources if item)))
                record.update(outcome="observed_success", reason="completed native write; Iris connection observed separately",
                              evidence=evidence)
            elif target and result.get("returncode") == 0:
                # Share the operation resource exclusion with writes. This is a
                # read-only acceptance attempt, never a replay of the request.
                _, status, _ = await service.operations.execute(
                    str(target), actor, "host.recovery.verify", {"source_operation_id": operation_id},
                    lambda: self.verify(str(target), before, params, 10),
                    exclusive_resources=tuple(sorted(item for item in resources if item)),
                )
                record.update(outcome="observed_success", reason="completed ROM write and live Vibe Mode verified",
                              evidence={"write_completed": True, "status": status})
        except (OSError, ValueError, LookupError, RuntimeError, asyncio.TimeoutError) as error:
            record["reason"] = str(error)
        return save_reconciliation(service.store, record)


def register_routes(app: web.Application, service: Any) -> None:
    async def submit(request: web.Request) -> web.Response:
        if not request_is_loopback(request) or request.headers.get("Origin"):
            raise PermissionError("host operations require a local CLI and a private request file")
        blocked = service.require_develop()
        if blocked is not None:
            return blocked
        if service.demo:
            raise ValueError("host operations require a physical device")
        body = await json_body(request)
        if set(body) != {"request_id"}:
            raise ValueError("host operations accept only a private request_id")
        operation = await service.host_operations.submit(str(body["request_id"]), request_actor(request))
        return web.json_response({"operation": operation,
                                  "status_url": "/v2/operations/" + operation["operation_id"]}, status=202)

    app.router.add_post("/v2/host-operations", submit)


__all__ = ["HostOperations", "active_workers", "register_routes"]
