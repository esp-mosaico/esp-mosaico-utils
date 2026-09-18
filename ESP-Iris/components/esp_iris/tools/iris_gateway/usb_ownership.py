"""Coordinate unresolved maintenance reservations before USB admission.

Records are protected by an OS lock, so a crashed Gateway cannot leave a stale
reservation blocking future starts. All registry transactions are synchronous;
the admission mutex must never be held across an await or a serial operation.
"""

from __future__ import annotations

import contextlib
import json
import uuid

from .discovery import serial_port_key
from .link import EndpointLock


class UsbEndpointBusy(RuntimeError):
    """Another session or maintenance reservation owns the USB interface."""


def reservation_selector(state: dict) -> str | None:
    for key in ("lock_endpoint", "endpoint"):
        endpoint = str(state.get(key) or "")
        if endpoint.startswith("usb:location="):
            return endpoint
    if state.get("location"):
        return "usb:location=" + str(state["location"])
    if state.get("serial_number"):
        return "usb:serial=" + str(state["serial_number"])
    endpoint = str(state.get("endpoint") or "")
    if endpoint.startswith("usb:serial="):
        return endpoint
    path = str(state.get("path") or endpoint[4:])
    if path.startswith("/dev/serial/by-path/"):
        return path
    # A tty/COM number or product-dependent by-id name is not evidence that a
    # newly enumerated board is the one from the persisted maintenance lease.
    return None


def _may_match(selector: str | None, metadata: dict) -> bool:
    if selector is None:
        return True
    if selector.startswith("usb:location="):
        location = metadata.get("location")
        return not location or selector == "usb:location=" + str(location)
    if selector.startswith("usb:serial="):
        serial = metadata.get("serial_number")
        return not serial or selector == "usb:serial=" + str(serial)
    current = str(metadata.get("path") or "")
    return (
        not current.startswith("/dev/serial/by-path/")
        or serial_port_key(selector) == serial_port_key(current)
    )


@contextlib.contextmanager
def usb_admission():
    lock = EndpointLock("usb-admission")
    try:
        lock.acquire(blocking=True)
        yield lock.path.parent
    finally:
        lock.close()


class UsbQuarantine:
    def __init__(self, state: dict) -> None:
        self.id = uuid.uuid4().hex
        self.lock = EndpointLock("usb-quarantine:" + self.id)
        self.path = self.lock.path.parent / ("usb-quarantine-" + self.id + ".json")
        try:
            self.lock.acquire()
            with usb_admission():
                self.path.write_text(json.dumps({
                    "selector": reservation_selector(state),
                    "endpoint": state["endpoint"],
                }), encoding="utf-8")
        except BaseException:
            self.lock.close()
            raise

    def close(self) -> None:
        with usb_admission():
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            self.lock.close()


def check_usb_quarantines(root, metadata: dict, *, ignore: str | None = None) -> None:
    """Called under usb_admission, before acquiring the physical endpoint lock."""
    for path in root.glob("usb-quarantine-*.json"):
        identity = path.stem[len("usb-quarantine-"):]
        if identity == ignore:
            continue
        lock = EndpointLock("usb-quarantine:" + identity)
        try:
            try:
                lock.acquire()
            except RuntimeError:
                record = json.loads(path.read_text(encoding="utf-8"))
                if _may_match(record["selector"], metadata):
                    raise UsbEndpointBusy(
                        "USB endpoint is owned by another ESP-Iris maintenance "
                        f"reservation ({record['endpoint']}); resolve or cancel it first"
                    ) from None
            else:
                path.unlink()
        finally:
            lock.close()
