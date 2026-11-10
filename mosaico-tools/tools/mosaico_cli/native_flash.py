"""Thin native IDF command adapter; Gateway only coordinates the serial port."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from .errors import BuildError, MosaicoError
from .gateway import (
    connected_devices,
    ensure_gateway,
    run_host_operation,
    select_device,
)
from .iris import host_api
from .project import resolve_project
from .runtime import idf_target_command, resolve_idf_path


def flash_application(arguments, context):
    project = resolve_project(context.workspace, arguments.project, Path.cwd(), native=True)
    target = arguments.command
    native = idf_target_command(context, idf_path=resolve_idf_path(context.workspace, project),
                                project=project, build_dir=project / "build", target=target,
                                port="{port}", timeout=arguments.timeout)
    extra = list(getattr(arguments, "idf_args", []))
    if extra[:1] == ["--"]:
        extra = extra[1:]
    native["argv"][-1:-1] = extra
    # Selection must not require an Iris handshake on the board being repaired.
    session = ensure_gateway(context, None, select=False)
    endpoint, device_id = arguments.endpoint, arguments.device_id
    if not endpoint:
        device = select_device(connected_devices(context, session), device_id)
        device_id = device["device_id"]
    reconnect_timeout = arguments.reconnect_timeout
    if reconnect_timeout is None:
        reconnect_timeout = 0 if arguments.monitor else 10
    try:
        spec = host_api(context.workspace).prepare_native_flash(
            project / "build", native, target=target, endpoint=endpoint,
            device_id=device_id, baudrate=arguments.baudrate,
            reconnect_timeout=reconnect_timeout)
    except (OSError, ValueError) as error:
        raise BuildError("Could not prepare native flash: " + str(error)) from error
    result = run_host_operation(context, session, spec, timeout=arguments.timeout)
    connection = result.get("evidence", {}).get("connection", {"state": "waiting"})
    context.status("flash: native write succeeded; Iris connection: " + connection["state"])
    if getattr(arguments, "run_app", False):
        from .run_app import run_application
        try:
            result["application_run"] = run_application(arguments, context, allow_running=True)
        except MosaicoError as error:
            error.details.update(flash_write_completed=True, flash_result=result)
            raise
    if arguments.monitor:
        from .commands import monitor
        if context.json_output:
            import json
            print(json.dumps({"kind": "flash_result", "ok": True, **result}), flush=True)
        monitor(SimpleNamespace(snapshot=False, timeout=0, grep=None), context, context.json_output,
                session=session, endpoint=result["endpoint"])
    return {"status": "succeeded", "flash_target": target, "project": str(project), **result}
