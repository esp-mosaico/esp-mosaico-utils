"""OTA message sequencing and timeout reconciliation for an established session.

DeviceSession retains link selection, request correlation and locking. This
module owns the OTA transaction, progress validation and cancellation cleanup.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import struct
from typing import TYPE_CHECKING, Any

from .protocol import Channel, OtaType, ProtocolError

if TYPE_CHECKING:
    from .session import DeviceSession, ProgressCallback


async def perform_ota_update(
    session: DeviceSession,
    image: bytes,
    *,
    expected_sha256: bytes | None = None,
    project_name: str = "",
    version: str = "",
    timeout: float = 10.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    if not image:
        raise ValueError("OTA image is empty")
    digest = expected_sha256 or hashlib.sha256(image).digest()
    if len(digest) != 32:
        raise ValueError("OTA SHA-256 must contain 32 bytes")
    project = project_name.encode()
    release = version.encode()
    if len(project) > 32 or len(release) > 32:
        raise ValueError("OTA project/version is too long")
    begin = (
        struct.pack("<I", len(image))
        + digest
        + bytes([len(project), len(release)])
        + b"\0\0"
        + project
        + release
    )
    if progress_callback is not None:
        await progress_callback(
            {
                "stage": "erasing",
                "bytes_received": 0,
                "bytes_total": len(image),
                "progress_permille": 0,
                "partition": "",
            }
        )
    # BEGIN prepares the image range on the device service worker. Allow
    # time for that erase. DATA requests retain their shorter deadlines.
    begin_timeout = max(timeout, session.OTA_BEGIN_TIMEOUT_SECONDS)
    frame = await session._request(
        Channel.OTA, OtaType.BEGIN, begin, begin_timeout
    )
    if frame.type != OtaType.BEGIN_RESPONSE or len(frame.payload) < 11:
        raise ProtocolError("unexpected OTA begin response")
    job_id, total_size, chunk_size = struct.unpack_from("<IIH", frame.payload)
    label_size = frame.payload[10]
    if (
        total_size != len(image)
        or chunk_size == 0
        or len(frame.payload) != 11 + label_size
    ):
        raise ProtocolError("invalid OTA begin response")
    partition = frame.payload[11:].decode("ascii", errors="replace")
    if progress_callback is not None:
        await progress_callback(
            {
                "stage": "transferring",
                "job_id": job_id,
                "bytes_received": 0,
                "bytes_total": len(image),
                "progress_permille": 0,
                "partition": partition,
            }
        )
    offset = 0
    end_confirmed_by_job = False
    end_confirmed_by_disconnect = False
    try:
        while offset < len(image):
            request_count = session.OTA_MAX_IN_FLIGHT
            batch: list[tuple[int, bytes]] = []
            batch_offset = offset
            while batch_offset < len(image) and len(batch) < request_count:
                chunk = image[batch_offset : batch_offset + chunk_size]
                batch.append((batch_offset, chunk))
                batch_offset += len(chunk)
            try:
                async with session._request_lock:
                    tasks = [
                        asyncio.create_task(
                            session._request_unlocked(
                                Channel.OTA,
                                OtaType.DATA,
                                struct.pack("<I", chunk_offset) + chunk,
                                timeout,
                            )
                        )
                        for chunk_offset, chunk in batch
                    ]
                    try:
                        data_responses = await asyncio.gather(*tasks)
                    except BaseException:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise
            except (asyncio.TimeoutError, TimeoutError):
                status = await session.ota_status(timeout=timeout)
                if not status["active"] or status["job_id"] != job_id:
                    raise TimeoutError(
                        f"OTA data response timed out; device status is {status}"
                    ) from None
                received = int(status["bytes_received"])
                accepted_offsets = {offset}
                accepted_offsets.update(
                    chunk_offset + len(chunk) for chunk_offset, chunk in batch
                )
                if received not in accepted_offsets:
                    raise ProtocolError(
                        f"OTA resumed at unexpected byte offset {received}"
                    )
                offset = received
                if progress_callback is not None:
                    await progress_callback(status)
                continue
            if len(batch) != len(data_responses):
                raise ProtocolError("OTA data response count does not match request batch")
            for (chunk_offset, chunk), data_response in zip(batch, data_responses):
                if (
                    data_response.type != OtaType.DATA_RESPONSE
                    or len(data_response.payload) != 8
                ):
                    raise ProtocolError("unexpected OTA data response")
                received, progress, reserved = struct.unpack(
                    "<IHH", data_response.payload
                )
                if received != chunk_offset + len(chunk) or reserved != 0:
                    raise ProtocolError("invalid OTA progress")
                offset = received
                if progress_callback is not None:
                    await progress_callback(
                        {
                            "stage": "transferring",
                            "job_id": job_id,
                            "bytes_received": received,
                            "bytes_total": len(image),
                            "progress_permille": progress,
                            "partition": partition,
                        }
                    )
        if progress_callback is not None:
            await progress_callback(
                {
                    "stage": "verifying",
                    "job_id": job_id,
                    "bytes_received": len(image),
                    "bytes_total": len(image),
                    "progress_permille": 950,
                    "partition": partition,
                }
            )
        try:
            end = await session._request(Channel.OTA, OtaType.END, b"", timeout)
        except (asyncio.TimeoutError, TimeoutError):
            job_status = await session.job(job_id)
            if (
                job_status.get("job_state") != "succeeded"
                or int(job_status.get("result", -1)) != 0
            ):
                raise TimeoutError(
                    f"OTA end response timed out; device Job is {job_status}"
                ) from None
            end_confirmed_by_job = True
            end = None
        except (ConnectionError, OSError):
            # Some USB CDC implementations restart immediately after
            # accepting OTA END, so Windows removes the COM endpoint before
            # the END_RESPONSE reaches the host. The gateway must still
            # validate the new boot identity/version before succeeding.
            end_confirmed_by_disconnect = True
            end = None
    except BaseException:
        with contextlib.suppress(Exception):
            await session._request(Channel.OTA, OtaType.CANCEL, b"", timeout)
        raise
    if not end_confirmed_by_job and not end_confirmed_by_disconnect:
        if end is None or end.type != OtaType.END_RESPONSE or len(end.payload) != 8:
            raise ProtocolError("unexpected OTA end response")
        returned_job, result = struct.unpack("<Ii", end.payload)
        if returned_job != job_id or result != 0:
            raise RuntimeError(f"OTA failed with device error 0x{result:08x}")
    return {
        "job_id": job_id,
        "bytes": len(image),
        "sha256": digest.hex(),
        "partition": partition,
        "restart_required": True,
        "completion_evidence": (
            "device_job"
            if end_confirmed_by_job
            else "session_close"
            if end_confirmed_by_disconnect
            else "end_response"
        ),
    }


async def ota_status(session: DeviceSession, *, timeout: float = 10.0) -> dict[str, Any]:
    frame = await session._request(Channel.OTA, OtaType.STATUS, b"", timeout)
    if frame.type != OtaType.STATUS or len(frame.payload) < 20:
        raise ProtocolError("unexpected OTA status response")
    job_id, total, received, progress = struct.unpack_from("<IIIH", frame.payload)
    active = bool(frame.payload[14])
    label_size = frame.payload[15]
    result = struct.unpack_from("<i", frame.payload, 16)[0]
    if len(frame.payload) != 20 + label_size:
        raise ProtocolError("invalid OTA status response")
    return {
        "stage": "transferring" if active else "idle",
        "job_id": job_id,
        "bytes_total": total,
        "bytes_received": received,
        "progress_permille": progress,
        "active": active,
        "result": result,
        "partition": frame.payload[20:].decode("ascii", errors="replace"),
    }
