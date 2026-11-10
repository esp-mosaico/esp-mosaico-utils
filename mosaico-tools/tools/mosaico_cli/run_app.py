"""Explicitly retry an application through Vibe's local Iris control link."""
from __future__ import annotations

import struct
import time

from .commands import _raw_rpc_payload
from .errors import DeviceError, OperationError, OutcomeUnknownError, SelectionError
from .evidence import _live_status
from .gateway import connected_devices, ensure_gateway, gateway_json, select_device


def run_application(arguments, context, *, allow_running=False):
    if getattr(arguments, "gateway_profile", None) and getattr(arguments, "endpoint", None):
        raise SelectionError("Select an external Gateway device with --device-id, not --endpoint.")
    session = ensure_gateway(context, getattr(arguments, "gateway_profile", None))
    selected = select_device(connected_devices(context, session), arguments.device_id)
    device_id = str(selected["device_id"])
    before = _live_status(context, session, device_id)
    result = {"command": "run-app", "device_id": device_id,
              "previous_boot_id": before["boot_id"], "log": str(context.log_path)}
    if allow_running and before.get("firmware_mode") == "normal":
        return {**result, "status": "already_running", "device": before}
    if (before.get("firmware_mode") != "recovery"
            or before.get("product_contract") != "esp-mosaico/v2"):
        raise DeviceError("Run-app requires a live ESP-Mosaico Vibe Mode session.")

    deadline = time.monotonic() + arguments.timeout
    context.status("run-app: requesting one application retry through Vibe Mode")
    # Never replay: a lost reply may mean the device already selected/restarted
    # the application. An older Vibe without method 8 must be updated first.
    try:
        reply = gateway_json(context, session, "rpc-raw", device_id, "0x1202", "8",
                             "--deadline-ms", "10000", timeout=min(arguments.timeout, 15))
        payload = _raw_rpc_payload(reply)
        if len(payload) != 36:
            raise DeviceError("Invalid application retry response.")
        address, = struct.unpack_from("<I", payload)
        expected_sha = payload[4:].hex()
        if not address or not any(payload[4:]):
            raise DeviceError("Missing application retry identity.")
    except DeviceError as error:
        raise OutcomeUnknownError(
            "Application retry was not acknowledged; the request was not repeated. "
            "Inspect the UART connection and current firmware. Older Vibe firmware "
            "requires an update to support run-app.", details=result,
        ) from error

    last = before
    while time.monotonic() < deadline:
        try:
            last = _live_status(context, session, device_id)
        except DeviceError:
            # UART may keep the same device node across both firmware images.
            last = None
        if last is not None and last["boot_id"] != before["boot_id"]:
            if last.get("firmware_mode") == "recovery":
                raise OperationError("The application returned to Vibe Mode; it was not retried again.",
                                     details={**result, "device": last})
            if last.get("firmware_mode") == "normal":
                if last.get("firmware_sha256") != expected_sha:
                    raise OperationError("The running application does not match the selected image.",
                                         details={**result, "device": last, "expected_sha256": expected_sha})
                return {**result, "status": "succeeded", "application_address": address,
                        "boot_id": last["boot_id"], "device": last}
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise OutcomeUnknownError(
        "Application retry was accepted, but its Iris session did not reconnect before the timeout. "
        "Check that the application uses the same UART pins and console baud rate; "
        "the request was not repeated.",
        details={**result, "application_address": address, "expected_sha256": expected_sha, "device": last},
    )
