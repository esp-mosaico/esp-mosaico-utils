# ESP-Mosaico Recovery

This component owns retained Recovery firmware, its reviewed bundle and the
public product ABI in `include/mosaico_recovery_contract.h`. The header is used
by independently built normal applications and Recovery. Its existing 64-byte
sysmeta record, NVS namespace, magic and version remain unchanged.

The product CLI and build runner now live in [mosaico-tools](../mosaico-tools/README.md).
The old `mosaico.py`, Python import path and build-runner entrypoint forward to
that implementation for compatibility. New consumers use `mosaico-tools`.
Integration and firmware tests remain under `tests/`.

Firmware and reviewed images stay under `firmware/recovery`; moving host tools
does not rebuild or replace the reviewed bundle. Perform device operations
through the consuming workspace's `mosaico.py` launcher.

## Recovery through an independent USB Serial/JTAG connection

When the same board has a separate USB Serial/JTAG cable connected, select its
port explicitly while the primary ESP-Iris connection is still live:

```sh
python mosaico.py recover --device-id DEVICE_ID --recovery-port COM14 --source current
```

Omit `--source current` to use the reviewed bundle. `--dry-run` resolves the live
identity and port without building, leasing, resetting or writing. This option
requires exactly one connected Espressif `303A:1001` interface, and the named
port must identify it. Selecting it asserts that this independently connected
interface belongs to the chosen board. For a device already in ROM download
mode, prefer `--hardware-mac`; its eFuse identity is read directly instead of
inferring an association from USB topology.

The command prepares the complete reviewed/current Recovery bundle before
maintenance. It acquires the primary device lease (including crash evidence)
and a separate physical endpoint lease, so Gateway sessions on both interfaces
are detached and their cross-process reservations remain held during flashing.
The serial interface is enumerated again before the write; an identity change,
ambiguous endpoint, conflicting owner or lease failure prevents flashing. A
Gateway that cannot reserve both interfaces fails closed. Other applications
must release the serial port; a busy port is an error, never an invitation to
force another session open.

Only the existing `mosaico-recover-flash` target writes firmware. Its complete
bundle writes bootloader, partition table, OTA selection data and factory
Recovery; this option does **not** introduce whole-flash erase or a
Recovery-partition-only mode. Preserve the normal bundle/layout contract.
Recovery acceptance uses the original managed connection: the same Device ID,
a new Boot ID and the prepared Recovery version must be verified before the
independent endpoint lease is released. The auxiliary lease is released with
an abort action because it represents only a transport reservation, not a
second acceptance result. Failure unwinds remaining leases, with quarantine
reported if cleanup fails.

`recovery-route.json` in the operation evidence directory records both lease
IDs, the selected USB identity and the original Device/Boot IDs, without lease
tokens. Gateway records retain the detailed before/after and crash evidence.

Recovery remote downloads now use [HTTPS Bridge](firmware/recovery/README.md).
Configure the build Origin and board ID, then use `mosaico.py iris test bridge-code` or
the device download page to pair once for a partitions, layout or factory update.
