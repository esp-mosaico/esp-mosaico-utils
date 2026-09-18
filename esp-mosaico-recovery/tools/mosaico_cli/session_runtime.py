"""Project-owned Gateway lifetimes. No detached global service is created."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import DeviceError, EnvironmentError
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
        raise DeviceError(f"Project Gateway rejected the request: {details or error.reason}") from error
    except (URLError, OSError, ValueError) as error:
        raise DeviceError(f"Project Gateway is unavailable: {error}") from error


class SessionScope:
    def __init__(self) -> None:
        self.arguments: Any = None
        self.sessions: dict[str, Any] = {}
        self.processes: list[tuple[subprocess.Popen, str, Path]] = []
        self.info: dict[str, Any] = {}
        self.owned_records: dict[Path, str] = {}

    def gateway(self, context: Any, python: Path, script: Path, revision: str) -> Any:
        from .gateway import GatewaySession, _require_compatible_gateway

        args = self.arguments
        project = resolve_project(context.workspace, getattr(args, "project", None), Path.cwd())
        project_key = hashlib.sha256((str(context.workspace.root.resolve()) + "\0" + str(project)).encode()).hexdigest()
        if project_key in self.sessions:
            return self.sessions[project_key]
        directory = state_root("esp-mosaico") / "project-sessions" / project_key
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
                if not existing.get("persistent"):
                    raise EnvironmentError("A temporary command owns this project session; wait for it to finish or use 'session run' for shared development")
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
            self.info = record
        selected = getattr(args, "device_id", None)
        endpoint = getattr(args, "endpoint", None)
        command = getattr(args, "command", "")
        # Transfer/release inspect existing ownership; acquiring implicitly
        # would defeat their explicit state transitions.
        if (selected or endpoint) and command not in {"device", "list"}:
            body = {"device_id": selected, "endpoint": endpoint}
            token_file = getattr(args, "pairing_token_file", None)
            if token_file:
                body["pairing_token"] = read_pairing_token(Path(token_file))
            acquired = request(record["url"], "/v1/project/acquire", body, timeout=35)
            if not selected:
                args.device_id = acquired["device"]["device_id"]
        return result

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
