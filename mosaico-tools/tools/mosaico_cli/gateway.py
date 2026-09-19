"""Manage ESP-Iris Gateway discovery and lifecycle for mosaico.py."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import (
    DeviceError,
    EnvironmentError,
    OperationError,
    OutcomeUnknownError,
    SelectionError,
)
from .host import (
    state_root,
    virtual_environment_python,
)
from .runtime import RunContext
from .workspace import WorkspaceConfig, user_path

REQUIRED_GATEWAY_API_MAJOR = 1
MAINTENANCE_CAPABILITY = "device-maintenance-lease/v1"
ENDPOINT_MAINTENANCE_CAPABILITY = "physical-endpoint-maintenance-lease/v1"
SYSTEM_INVENTORY_CAPABILITY = "system-inventory/v1"
MOSAICO_COMPATIBILITY_JSON = json.dumps({
    "chip_target": "esp32s31",
    "product_contract": "esp-mosaico/v1",
    "board_id": "esp-mosaico",
    "layout_id": "mosaico-retained-recovery-2m-v1",
    "recovery_abi": 1,
}, separators=(",", ":"))


def _python_major_minor(python: Path) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                str(python),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)", result.stdout.strip())
    if result.returncode or match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def iris_environment_root(source: Path) -> Path:
    """Select an isolated Gateway environment for the active Python runtime."""

    desired = sys.version_info.major, sys.version_info.minor
    legacy = source / ".venv"
    legacy_python = virtual_environment_python(legacy)
    if legacy_python.is_file() and _python_major_minor(legacy_python) == desired:
        return legacy
    source_key = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
    return (
        state_root("esp-mosaico")
        / "runtimes"
        / "esp-iris"
        / source_key
        / f"py{desired[0]}.{desired[1]}"
    )


def locate_iris_tools(workspace: WorkspaceConfig) -> tuple[Path, Path]:
    source = workspace.esp_iris_path
    script = source / "components" / "esp_iris" / "tools" / "esp_iris.py"
    python = virtual_environment_python(iris_environment_root(source))
    if not script.is_file():
        raise EnvironmentError(
            f"The configured ESP-Iris checkout is unavailable: {source}. "
            "Initialize the workspace dependency and try again."
        )
    if not python.is_file():
        raise EnvironmentError(
            f"The pinned ESP-Iris host environment is unavailable: {python}"
        )
    return user_path(python), user_path(script)


def ensure_iris_tools(context: RunContext) -> tuple[Path, Path]:
    source = context.workspace.esp_iris_path
    tools = source / "components" / "esp_iris" / "tools"
    script = tools / "esp_iris.py"
    lock = tools / "requirements.lock"
    if not script.is_file() or not lock.is_file():
        raise EnvironmentError(
            "The pinned ESP-Iris checkout or its host dependency lock is unavailable."
        )
    environment_root = iris_environment_root(source)
    python = virtual_environment_python(environment_root)
    marker = environment_root / ".mosaico-requirements"
    fingerprint = (
        f"python={sys.version_info.major}.{sys.version_info.minor}\n"
        f"requirements={hashlib.sha256(lock.read_bytes()).hexdigest()}\n"
    )
    current = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    desired = sys.version_info.major, sys.version_info.minor
    if python.is_file() and _python_major_minor(python) != desired:
        result = context.run(
            [sys.executable, "-m", "venv", "--clear", environment_root],
            timeout=120,
        )
        if result.returncode:
            raise EnvironmentError(
                "Could not refresh the pinned ESP-Iris host environment."
            )
        current = ""
    if not python.is_file():
        if sys.version_info < (3, 8):  # noqa: UP036 -- diagnose unsupported host interpreters
            raise EnvironmentError("ESP-Iris host runtime requires Python 3.8 or newer.")
        result = context.run(
            [sys.executable, "-m", "venv", environment_root], timeout=120
        )
        if result.returncode:
            raise EnvironmentError("Could not create the pinned ESP-Iris host environment.")
    if current != fingerprint:
        result = context.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--requirement",
                lock,
            ],
            timeout=600,
        )
        if result.returncode:
            raise EnvironmentError("Could not install the pinned ESP-Iris host dependencies.")
        marker.write_text(fingerprint, encoding="utf-8")
    return user_path(python), user_path(script)


@dataclass(frozen=True)
class GatewaySession:
    python: Path
    script: Path
    connection_args: tuple[str, ...]
    profile: str | None
    started_local: bool

    def ctl_argv(self, *arguments: str, json_output: bool = True) -> list[str]:
        result = [str(self.python), str(self.script), "ctl", *self.connection_args]
        if json_output:
            result.append("--json")
        result.extend(arguments)
        return result


def _decode_json(output: str) -> Any:
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise OperationError("ESP-Iris returned an invalid result.") from error


def _probe(
    context: RunContext,
    python: Path,
    script: Path,
    connection: tuple[str, ...],
) -> bool:
    try:
        result = context.run(
            [python, script, "ctl", *connection, "--json", "devices"], timeout=4
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode:
        return False
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict) and isinstance(value.get("devices"), list)


def _gateway_health(
    context: RunContext,
    python: Path,
    script: Path,
    connection: tuple[str, ...],
) -> dict[str, Any] | None:
    try:
        result = context.run(
            [python, script, "ctl", *connection, "--json", "health"], timeout=4
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _require_compatible_gateway(
    health: dict[str, Any] | None,
    *,
    expected_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api = health.get("gateway_api") if isinstance(health, dict) else None
    capabilities = health.get("capabilities") if isinstance(health, dict) else None
    if not isinstance(api, dict) or api.get("major") != REQUIRED_GATEWAY_API_MAJOR:
        raise EnvironmentError(
            "The reachable ESP-Iris Gateway does not implement the required API version."
        )
    if not isinstance(capabilities, list):
        raise EnvironmentError("The reachable ESP-Iris Gateway did not report capabilities.")
    assert isinstance(health, dict)
    if expected_source is not None:
        actual = health.get("source")
        if (not isinstance(actual, dict) or any(actual.get(key) != expected_source.get(key)
                                               for key in ("algorithm", "fingerprint"))):
            raise EnvironmentError(
                "The local Iris Gateway source fingerprint differs under "
                "gateway.source_policy=exact; it was not stopped."
            )
    return health


def _pinned_source_revision(source: Path) -> str:
    # Historical name retained for callers: this is provenance, not the
    # compatibility boundary, and a source archive does not require Git.
    from types import SimpleNamespace
    from .iris import host_api

    identity = host_api(SimpleNamespace(esp_iris_path=source)).source_identity(source)
    return identity["git_revision"] or "sha256:" + identity["fingerprint"]


def _is_local_session(session: GatewaySession) -> bool:
    if session.profile is not None or len(session.connection_args) != 2:
        return False
    if session.connection_args[0] != "--url":
        return False
    parsed = urlsplit(session.connection_args[1])
    return parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def ensure_gateway(context: RunContext, profile: str | None, *, start: bool = True,
                   select: bool = True) -> GatewaySession:
    if start or profile:
        python, script = ensure_iris_tools(context)
    else:
        # Status/ownership requests use HTTP only; never bootstrap a host venv
        # just to find out that a project has no running Gateway.
        python = Path(sys.executable)
        script = context.workspace.esp_iris_path / "components/esp_iris/tools/esp_iris.py"
    if profile:
        connection = ("--profile", profile)
        if not _probe(context, python, script, connection):
            raise DeviceError(f"Gateway profile is unreachable: {profile}")
        _require_compatible_gateway(_gateway_health(context, python, script, connection))
        return GatewaySession(python, script, connection, profile, False)

    expected_revision = _pinned_source_revision(context.workspace.esp_iris_path)
    from .session_runtime import CURRENT_SCOPE
    scope = CURRENT_SCOPE.get()
    if scope is not None:
        return scope.gateway(context, python, script, expected_revision, start=start, select=select)
    raise EnvironmentError("Local Gateway operations require a project SessionScope; use mosaico.py or an explicit remote profile.")


def gateway_json(
    context: RunContext,
    session: GatewaySession,
    *arguments: str,
    timeout: float = 15,
    environment: dict[str, str] | None = None,
    stdin_text: str | None = None,
    sensitive_output: bool = False,
) -> Any:
    from .session_runtime import CURRENT_SCOPE
    scope = CURRENT_SCOPE.get()
    if scope is not None:
        for lease in scope.leases.values():
            lease.check()
    try:
        result = context.run(
            session.ctl_argv(*arguments),
            timeout=timeout,
            env=environment,
            input_text=stdin_text,
            sensitive_output=sensitive_output,
        )
    except subprocess.TimeoutExpired as error:
        raise DeviceError("The ESP-Iris Gateway request timed out.") from error
    if result.returncode:
        raise DeviceError(
            "The ESP-Iris Gateway request failed.",
            details={"log": str(context.log_path)},
        )
    return _decode_json(result.stdout)


def system_inventory(
    context: RunContext,
    session: GatewaySession,
    device_id: str,
) -> dict[str, Any]:
    """Read and validate the device's live system inventory."""

    health = gateway_json(context, session, "health")
    capabilities = health.get("capabilities", []) if isinstance(health, dict) else []
    if SYSTEM_INVENTORY_CAPABILITY not in capabilities:
        raise EnvironmentError(
            "The reachable ESP-Iris Gateway does not support partition-table "
            "preflight checks. Update or restart it from the pinned ESP-Iris checkout."
        )
    value = gateway_json(
        context,
        session,
        "system-inventory",
        device_id,
    )
    inventory = value.get("inventory") if isinstance(value, dict) else None
    if not isinstance(inventory, dict):
        raise DeviceError("ESP-Iris returned an invalid system inventory.")
    partition_hash = inventory.get("partition_table_sha256")
    if not isinstance(partition_hash, str) or re.fullmatch(
        r"[0-9a-fA-F]{64}", partition_hash
    ) is None:
        raise DeviceError(
            "The device did not report a valid partition-table SHA-256."
        )
    return {**inventory, "partition_table_sha256": partition_hash.lower()}


def enter_recovery_and_wait(
    context: RunContext,
    session: GatewaySession,
    device_id: str,
    *,
    previous_boot_id: str | int | None,
    timeout: float,
) -> dict[str, Any]:
    """Enter retained Recovery and wait for the same device to reconnect."""

    health = gateway_json(context, session, "health")
    if "recovery-transition/v1" not in health.get("capabilities", []):
        raise EnvironmentError("Gateway does not support the Recovery transition contract; update its host tools first")
    wait_timeout = min(max(timeout, 1), 30)
    value = gateway_json(context, session, "factory", device_id, "--wait",
                         "--wait-timeout", str(wait_timeout), timeout=wait_timeout + 10)
    status = value.get("recovery", {})
    boot_id = status.get("boot_id")
    if (status.get("device_id") != device_id or status.get("firmware_mode") != "recovery"
            or boot_id in (None, "") or str(boot_id) == str(previous_boot_id)):
        raise OperationError("Gateway did not confirm the selected device's Recovery transition")
    return status


def acquire_maintenance_lease(
    context: RunContext,
    session: GatewaySession,
    *,
    device_id: str,
    expected_version: str,
    timeout: float,
) -> dict[str, Any]:
    if not _is_local_session(session):
        raise DeviceError("Remote Recovery is not supported; use the local Gateway.")
    health = gateway_json(context, session, "health")
    capabilities = health.get("capabilities", []) if isinstance(health, dict) else []
    if MAINTENANCE_CAPABILITY not in capabilities:
        raise EnvironmentError(
            "The local ESP-Iris Gateway does not support device maintenance leases."
        )
    value = gateway_json(
        context,
        session,
        "maintenance-acquire",
        device_id,
        "--expected-version",
        expected_version,
        "--wait-timeout",
        str(min(timeout, 60)),
        "--ttl-seconds",
        str(timeout + 60),
        timeout=min(timeout, 75),
        sensitive_output=True,
    )
    lease = value.get("lease") if isinstance(value, dict) else None
    if not isinstance(lease, dict) or not lease.get("lease_id") or not lease.get("token"):
        raise DeviceError("ESP-Iris returned an invalid maintenance lease.")
    endpoint = lease.get("endpoint")
    if not isinstance(endpoint, dict) or not (
        endpoint.get("path") or str(endpoint.get("endpoint") or "").startswith("usb:")
    ):
        try:
            finish_maintenance_lease(
                context, session, lease, abort=True, timeout=min(timeout, 30)
            )
        except DeviceError:
            pass
        raise DeviceError("The maintenance lease did not include a writable local port.")
    return lease


def acquire_endpoint_maintenance_lease(
    context: RunContext,
    session: GatewaySession,
    *,
    endpoint: str,
    expected_version: str,
    timeout: float,
) -> dict[str, Any]:
    if not _is_local_session(session):
        raise DeviceError("Remote Recovery is not supported; use the local Gateway.")
    health = gateway_json(context, session, "health")
    capabilities = health.get("capabilities", []) if isinstance(health, dict) else []
    if ENDPOINT_MAINTENANCE_CAPABILITY not in capabilities:
        raise EnvironmentError(
            "The local ESP-Iris Gateway does not support physical endpoint maintenance leases."
        )
    value = gateway_json(
        context,
        session,
        "maintenance-acquire-endpoint",
        endpoint,
        "--expected-version",
        expected_version,
        "--wait-timeout",
        str(min(timeout, 60)),
        "--ttl-seconds",
        str(timeout + 60),
        timeout=min(timeout, 75),
        sensitive_output=True,
    )
    lease = value.get("lease") if isinstance(value, dict) else None
    if not isinstance(lease, dict) or not lease.get("lease_id") or not lease.get("token"):
        raise DeviceError("ESP-Iris returned an invalid maintenance lease.")
    leased_endpoint = lease.get("endpoint")
    if not isinstance(leased_endpoint, dict) or not (
        leased_endpoint.get("path")
        or str(leased_endpoint.get("endpoint") or "").startswith("usb:")
    ):
        try:
            finish_maintenance_lease(
                context, session, lease, abort=True, timeout=min(timeout, 30)
            )
        except DeviceError:
            pass
        raise DeviceError("The maintenance lease did not include a writable local port.")
    return lease


def finish_maintenance_lease(
    context: RunContext,
    session: GatewaySession,
    lease: dict[str, Any],
    *,
    abort: bool,
    timeout: float,
) -> dict[str, Any]:
    token = str(lease.get("token") or "")
    lease_id = str(lease.get("lease_id") or "")
    if not token or not lease_id:
        raise DeviceError("The maintenance lease credentials are unavailable.")
    environment = os.environ.copy()
    environment["ESP_IRIS_MAINTENANCE_TOKEN"] = token
    arguments = [
        "maintenance-abort" if abort else "maintenance-complete",
        lease_id,
    ]
    if not abort:
        arguments.extend(["--timeout", str(timeout)])
    value = gateway_json(
        context,
        session,
        *arguments,
        timeout=timeout + 15,
        environment=environment,
    )
    result = value.get("lease") if isinstance(value, dict) else None
    if not isinstance(result, dict):
        raise DeviceError("ESP-Iris returned an invalid maintenance completion result.")
    return result


def renew_maintenance_lease(
    context: RunContext,
    session: GatewaySession,
    lease: dict[str, Any],
    *,
    ttl_seconds: float,
) -> dict[str, Any]:
    token = str(lease.get("token") or "")
    lease_id = str(lease.get("lease_id") or "")
    if not token or not lease_id:
        raise DeviceError("The maintenance lease credentials are unavailable.")
    environment = os.environ.copy()
    environment["ESP_IRIS_MAINTENANCE_TOKEN"] = token
    value = gateway_json(
        context,
        session,
        "maintenance-renew",
        lease_id,
        "--ttl-seconds",
        str(ttl_seconds),
        environment=environment,
    )
    result = value.get("lease") if isinstance(value, dict) else None
    if not isinstance(result, dict):
        raise DeviceError("ESP-Iris returned an invalid maintenance renewal result.")
    return result


def gateway_devices(
    context: RunContext,
    session: GatewaySession,
    *,
    wait_seconds: float = 5,
) -> list[dict[str, Any]]:
    """Return connected and cached devices, waiting briefly for live discovery."""

    deadline = time.monotonic() + wait_seconds
    while True:
        value = gateway_json(context, session, "devices")
        if not isinstance(value, dict):
            raise DeviceError("ESP-Iris returned an invalid device list.")
        devices = [
            item for item in value.get("devices", []) if isinstance(item, dict)
        ]
        if (
            any(item.get("connected") is not False for item in devices)
            or time.monotonic() >= deadline
        ):
            return devices
        time.sleep(0.25)


def connected_devices(
    context: RunContext,
    session: GatewaySession,
    *,
    wait_seconds: float = 5,
) -> list[dict[str, Any]]:
    return [
        item
        for item in gateway_devices(context, session, wait_seconds=wait_seconds)
        if item.get("connected") is not False
    ]


def select_device(devices: list[dict[str, Any]], requested: str | None) -> dict[str, Any]:
    if requested:
        matches = [item for item in devices if item.get("device_id") == requested]
        if len(matches) == 1:
            return matches[0]
        raise DeviceError(f"The requested device is currently unavailable: {requested}")
    if len(devices) == 1:
        return devices[0]
    if not devices:
        raise DeviceError("No available ESP-Mosaico device was found.")
    raise SelectionError(
        "Multiple devices were found; specify one with --device-id.",
        details={"candidates": [item.get("device_id") for item in devices]},
    )


def _wait_gateway_operation(
    context: RunContext,
    session: GatewaySession,
    *,
    result: subprocess.CompletedProcess[str],
    started: float,
    timeout: float,
    action: str,
    progress_prefix: str,
) -> dict[str, Any]:
    try:
        value = _decode_json(result.stdout)
    except OperationError:
        value = {}
    operation = value.get("operation", value) if isinstance(value, dict) else {}
    if not isinstance(operation, dict):
        operation = {}
    operation_id = str(operation.get("operation_id") or "")
    status = operation.get("status")
    if result.returncode:
        if status in {"outcome_unknown", "unknown"} or status is None:
            raise OutcomeUnknownError(
                f"The {action.lower()} submission outcome is unknown; the write "
                "operation will not be replayed automatically.",
                details={"result": value, "log": str(context.log_path)},
            )
        raise OperationError(
            f"{action} submission failed.",
            details={"result": value, "log": str(context.log_path)},
        )
    if not operation_id or status in {"outcome_unknown", "unknown"} or status is None:
        raise OutcomeUnknownError(
            f"The {action.lower()} outcome is unknown; the write operation will not be "
            "replayed automatically.",
            details={"result": value, "log": str(context.log_path)},
        )

    terminal = {
        "succeeded",
        "success",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
        "outcome_unknown",
        "unknown",
    }
    last_stage = ""
    last_bucket = -1
    while status not in terminal:
        if time.monotonic() - started >= timeout:
            raise OutcomeUnknownError(
                f"{action} timed out and the device outcome is unknown; the write "
                "operation will not be replayed automatically.",
                details={"operation_id": operation_id, "log": str(context.log_path)},
            )
        progress = operation.get("progress")
        progress = progress if isinstance(progress, dict) else {}
        stage = str(progress.get("stage") or status)
        permille = max(0, min(int(progress.get("progress_permille") or 0), 1000))
        bucket = permille // 50
        if stage != last_stage or bucket != last_bucket:
            detail = f"{progress_prefix}: {stage} {permille / 10:.1f}%"
            received = int(progress.get("bytes_received") or 0)
            total = int(progress.get("bytes_total") or 0)
            if total > 0:
                detail += f" ({received}/{total} bytes)"
            context.status(detail)
            last_stage = stage
            last_bucket = bucket
        time.sleep(0.25)
        try:
            current = gateway_json(context, session, "ota-status", operation_id)
        except DeviceError:
            from .session_runtime import CURRENT_SCOPE

            scope = CURRENT_SCOPE.get()
            current = scope.finished_operation(session, operation_id) if scope is not None else None
            if current is None:
                raise
            context.note(f"Gateway exited; read committed operation {operation_id} from this project session's store")
        operation = current.get("operation", current) if isinstance(current, dict) else {}
        if not isinstance(operation, dict):
            operation = {}
        status = operation.get("status")
        if status is None:
            raise OutcomeUnknownError(
                f"The {action.lower()} status response is invalid; the write operation will "
                "not be replayed automatically.",
                details={"operation_id": operation_id, "result": current,
                         "log": str(context.log_path)},
            )

    progress = operation.get("progress")
    progress = progress if isinstance(progress, dict) else {}
    context.status(
        f"{progress_prefix}: {progress.get('stage', status)} "
        f"{int(progress.get('progress_permille') or 0) / 10:.1f}%"
    )
    if status not in {"succeeded", "success", "completed"}:
        device_error = operation.get("error")
        diagnostic = str(device_error).strip() if device_error else None
        message = f"{action} failed: {status}"
        if diagnostic:
            message += f" ({diagnostic})"
        details = {"result": operation, "log": str(context.log_path)}
        if diagnostic:
            details["diagnostic"] = diagnostic
        raise OperationError(
            message,
            details=details,
        )
    if isinstance(value, dict):
        value["operation"] = operation
        return value
    return {"operation": operation}


def run_ota(
    context: RunContext,
    session: GatewaySession,
    *,
    device_id: str,
    image: Path,
    elf: Path,
    map_file: Path,
    validation: str,
    timeout: float,
    preconditions: dict[str, str] | None = None,
) -> dict[str, Any]:
    del validation
    if preconditions:
        health = gateway_json(context, session, "health")
        if "recovery-preconditions/v1" not in health.get("capabilities", []):
            raise EnvironmentError("Gateway cannot enforce Recovery preconditions; update its host tools before installing")
    started = time.monotonic()
    try:
        result = context.run(
            session.ctl_argv(
                "ota",
                device_id,
                str(image),
                "--elf",
                str(elf),
                "--map",
                str(map_file),
                "--execution-mode",
                "recovery",
                "--compatibility-json",
                MOSAICO_COMPATIBILITY_JSON,
                "--preconditions-json", json.dumps(preconditions or {}),
            ),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise OutcomeUnknownError(
            "Installation timed out and the device outcome is unknown; the write "
            "operation will not be replayed automatically.",
            details={"log": str(context.log_path)},
        ) from error
    return _wait_gateway_operation(
        context,
        session,
        result=result,
        started=started,
        timeout=timeout,
        action="Installation",
        progress_prefix="ota",
    )


def run_system_update_bundle(
    context: RunContext,
    session: GatewaySession,
    *,
    device_id: str,
    bundle: Path,
    timeout: float,
) -> dict[str, Any]:
    """Submit one reviewed local System Update bundle and wait for validation."""

    started = time.monotonic()
    try:
        result = context.run(
            session.ctl_argv(
                "system-update", device_id, str(bundle),
                "--compatibility-json",
                MOSAICO_COMPATIBILITY_JSON,
            ),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise OutcomeUnknownError(
            "System update submission timed out and the device outcome is unknown; "
            "the write operation will not be replayed automatically.",
            details={"log": str(context.log_path)},
        ) from error
    return _wait_gateway_operation(
        context,
        session,
        result=result,
        started=started,
        timeout=timeout,
        action="System update",
        progress_prefix="system update",
    )
