"""Project-owned Gateway lifetimes. No detached global service is created."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import DeviceError, EnvironmentError, GatewayNotRunningError, SelectionError
from .host import state_root
from .project import resolve_project

CURRENT_SCOPE: ContextVar[Any] = ContextVar("mosaico_project_scope", default=None)


def read_pairing_token(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) != 64 or len(bytes.fromhex(value)) != 32:
            raise ValueError("invalid token length")
        return value
    except (OSError, ValueError) as error:
        raise EnvironmentError(f"Pairing token file must contain 64 hexadecimal characters: {path}") from error


def request(url: str, path: str, body: dict[str, Any] | None = None,
            *, timeout: float = 20) -> dict[str, Any]:
    raw = json.dumps(body).encode() if body is not None else None
    req = Request(url + path, data=raw, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            details = json.loads(error.read())
        except (ValueError, OSError):
            details = {}
        remote_error = details.get("error") if isinstance(details, dict) else None
        if isinstance(remote_error, dict) and remote_error.get("code") == "selection_error":
            raise SelectionError(remote_error.get("message", "Select a device."),
                                 details=remote_error.get("details", {})) from error
        raise DeviceError(f"Project Gateway rejected the request: {details or error.reason}") from error
    except (URLError, OSError, ValueError) as error:
        raise DeviceError(f"Project Gateway is unavailable: {error}") from error


def acquire_device(url: str, arguments: Any, context: Any, *, allow_none: bool = False) -> dict[str, Any] | None:
    """Resolve and pin one live device for the rest of this command."""
    selected = getattr(arguments, "device_id", None)
    endpoint = getattr(arguments, "endpoint", None)
    body = {"device_id": selected, "endpoint": endpoint,
            "auto": not (selected or endpoint), "allow_none": allow_none}
    token_file = getattr(arguments, "pairing_token_file", None)
    if token_file:
        body["pairing_token"] = read_pairing_token(Path(token_file))
    device = request(url, "/v1/project/acquire", body, timeout=35)["device"]
    if device is not None:
        arguments.device_id = device["device_id"]
        context.status(f"device: {'selected' if selected or endpoint else 'automatically selected'} "
                       f"{device['device_id']} endpoint={device.get('endpoint', '')}")
    return device


class SessionScope:
    def __init__(self) -> None:
        self.arguments: Any = None
        self.sessions: dict[str, Any] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.processes: list[tuple[subprocess.Popen, str, Path]] = []
        self.info: dict[str, Any] = {}
        self.owned_records: dict[Path, str] = {}

    def gateway(self, context: Any, python: Path, script: Path, revision: str, *, start: bool = True) -> Any:
        from .gateway import GatewaySession, _require_compatible_gateway

        args = self.arguments
        project = resolve_project(context.workspace, getattr(args, "project", None), Path.cwd())
        project_key = hashlib.sha256((str(context.workspace.root.resolve()) + "\0" + str(project)).encode()).hexdigest()
        if project_key in self.sessions:
            return self.sessions[project_key]
        directory = state_root("esp-mosaico") / "project-sessions" / project_key
        if not start and not directory.exists():
            raise GatewayNotRunningError("This project's Gateway is not running; start 'iris run' first.")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection_file = directory / "connection.json"
        # This module is dependency-free; the source Link lock imports no
        # serial/network packages. Use the same cross-platform implementation.
        sys.path.insert(0, str(script.parent))
        from iris_gateway.link import EndpointLock

        lock = EndpointLock("project-start:" + project_key, root=directory / "locks")
        with contextlib.ExitStack() as cleanup:
            cleanup.callback(lock.close)
            lock.acquire(blocking=True)
            existing = None
            try:
                record = json.loads(connection_file.read_text(encoding="utf-8"))
                health = request(record["url"], "/v1/health", timeout=2)
                live = health.get("project_session") or {}
                if (live.get("session_id"), live.get("project_id"), live.get("instance_id")) != (
                    record["session_id"], project_key, record["instance_id"],
                ):
                    raise EnvironmentError("Project Gateway identity differs from the connection record")
                _require_compatible_gateway(health, expected_revision=revision)
                existing = live
            except (OSError, ValueError, KeyError, DeviceError):
                pass
            if existing:
                inspecting = getattr(args, "session_action", None) == "status"
                if not existing.get("persistent") and not inspecting:
                    raise EnvironmentError("A temporary command owns this project session; wait for it to finish or use 'iris run' for shared development")
                record = existing
                started = False
            else:
                # A failed HTTP probe is not proof that the owner died. The
                # Gateway holds this lock for its entire process lifetime.
                live_lock = EndpointLock("project:" + project_key,
                                         root=state_root("esp-mosaico") / "ownership" / "locks")
                try:
                    live_lock.acquire()
                except RuntimeError as error:
                    raise EnvironmentError("This project's Gateway is alive but unavailable; inspect its log before retrying") from error
                finally:
                    live_lock.close()
                if not start:
                    raise GatewayNotRunningError("This project's Gateway is not running; start 'iris run' first.")
                session_id = str(uuid.uuid4())
                instance_id = "project-" + session_id
                with contextlib.suppress(FileNotFoundError):
                    connection_file.unlink()
                environment = os.environ.copy()
                environment["ESP_IRIS_SOURCE_REVISION"] = revision
                token_file = getattr(args, "pairing_token_file", None)
                if token_file:
                    environment["ESP_IRIS_PAIRING_TOKEN"] = read_pairing_token(Path(token_file))
                # Decoder context must not silently come from another project.
                from .host import HostEnvironmentError, prepare_idf_environment
                from .runtime import resolve_idf_path
                try:
                    prepared = prepare_idf_environment(resolve_idf_path(context.workspace, project), base_environment=environment)
                    environment.update(prepared.values)
                    environment["ESP_IRIS_IDF_PATH"] = str(prepared.root)
                    environment["ESP_IRIS_IDF_PYTHON"] = str(prepared.python)
                except (EnvironmentError, HostEnvironmentError):
                    pass
                log = (directory / "gateway.log").open("a", encoding="utf-8")
                try:
                    process = subprocess.Popen([
                        str(python), str(script), "web", "--listen", "127.0.0.1", "--port", "0",
                        "--instance-id", instance_id, "--state-dir", str(directory / "state"),
                        "--project-session-id", session_id, "--project-id", project_key,
                        "--project-path", str(project), "--project-connection-file", str(connection_file),
                        "--ownership-dir", str(state_root("esp-mosaico") / "ownership"),
                        "--owner-stdin", "--no-tls",
                        *(["--project-persistent"] if getattr(args, "session_action", None) == "run" else []),
                    ], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                        env=environment, close_fds=True,
                        **({"start_new_session": True} if os.name != "nt" else {
                            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
                        }))
                except OSError as error:
                    raise EnvironmentError(f"Could not launch this project's Gateway: {error}") from error
                finally:
                    log.close()
                self.processes.append((process, "", connection_file))
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise EnvironmentError(f"Project Gateway exited; inspect {directory / 'gateway.log'}")
                    try:
                        record = json.loads(connection_file.read_text(encoding="utf-8"))
                        if record["session_id"] == session_id:
                            health = request(record["url"], "/v1/health", timeout=2)
                            _require_compatible_gateway(health, expected_revision=revision)
                            break
                    except (OSError, ValueError, KeyError, DeviceError):
                        pass
                    time.sleep(0.1)
                else:
                    raise EnvironmentError("Project Gateway startup timed out")
                self.processes[-1] = (process, record["url"], connection_file)
                self.owned_records[connection_file] = session_id
                started = True
            result = GatewaySession(python, script, ("--url", record["url"]), None, started)
            self.sessions[project_key] = result
            self.records[project_key] = dict(record)
            self.info = record
        if start:
            mode = "persistent" if getattr(args, "session_action", None) == "run" else "temporary"
            action = f"created {mode}" if started else "reusing"
            context.status(f"gateway: project={project} {action} Gateway at {record['url']}")
        selected = getattr(args, "device_id", None)
        endpoint = getattr(args, "endpoint", None)
        command = getattr(args, "command", "")
        # Discovery/status stay passive. Ownership management has separate
        # selection rules. A ROM hardware MAC is never an implicit USB selector.
        automatic = command in {
            "monitor", "memory", "crash", "rpc", "install", "system-update",
            "enter-recovery", "recovery-wifi", "bridge-code", "recover",
        } and not getattr(args, "hardware_mac", None)
        if command not in {"device", "list"} and (selected or endpoint or automatic):
            acquire_device(record["url"], args, context, allow_none=command == "recover")
        return result

    def finished_operation(self, session: Any, operation_id: str) -> dict[str, Any] | None:
        """Read committed evidence after this local Gateway has stopped.

        The owner may finish draining between a follower's status polls. Never
        restart a Gateway or replay a write just to obtain its final result.
        """
        project_key = next((key for key, value in self.sessions.items() if value is session), None)
        if project_key is None:
            return None  # Remote profiles have no registered local store.
        from iris_gateway.link import EndpointLock
        from iris_gateway.store import GatewayStore

        record = self.records[project_key]
        root = state_root("esp-mosaico")
        lock = EndpointLock("project:" + project_key, root=root / "ownership" / "locks")
        # HTTP may close just before the Gateway releases its lifetime lock.
        deadline = time.monotonic() + 2
        try:
            while True:
                try:
                    lock.acquire()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        return None
                    time.sleep(0.05)
            database = root / "project-sessions" / project_key / "state" / "gateway.sqlite3"
            with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None or row["created_ns"] < record["created_ns"] or not row["finished_ns"]:
                return None
            if row["status"] not in {"succeeded", "failed", "cancelled", "interrupted", "outcome_unknown"}:
                return None
            return GatewayStore._operation_row(row)
        except (OSError, sqlite3.Error, ValueError, KeyError):
            return None
        finally:
            lock.close()

    def close(self) -> None:
        for process, url, connection_file in reversed(self.processes):
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                # EOF tells Gateway to drain even if this CLI is interrupted.
                # Wait for it: a temporary command owns the entire workflow.
                deadline = time.monotonic() + 915
                while process.poll() is None and time.monotonic() < deadline:
                    try:
                        process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        continue
                    except KeyboardInterrupt:
                        continue
                if process.poll() is None:
                    raise EnvironmentError("Project Gateway is still draining; inspect its operation and maintenance records")
            if url:
                with contextlib.suppress(OSError, ValueError):
                    record = json.loads(connection_file.read_text(encoding="utf-8"))
                    if record.get("session_id") == self.owned_records.get(connection_file):
                        connection_file.unlink()
