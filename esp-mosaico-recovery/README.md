# ESP-Mosaico Recovery

Workspace-consumed command-line tools for ESP-Mosaico development and device
operations. A firmware workspace pins the containing `esp-mosaico-utils`
repository; the CLI package does not need to be installed into the user's
Python environment.

Local Gateways belong to project sessions. Keep one alive with
`python mosaico.py iris run --project <application>`; its printed URL opens
the Web workbench. Other commands for that project reuse it, while separate
projects get separate ports, databases, and logs. Ctrl-C in the owning terminal
drains and closes its Gateway. Without a persistent session, a device command
owns a temporary Gateway until it finishes.

Discovery/status queries do not open unclaimed devices. Device operations can
omit their target: prefer the sole connected device, then the sole existing
ownership (wait for that identity if offline), then the sole available USB
device from live enumeration. Multiple candidates report a selection error.
Unconnected TCP/mDNS endpoints, cached history, ROM and Serial/JTAG interfaces
are not automatic USB candidates. Explicit targets never fall back to another
device, and reservations held by other sessions are never automatically reclaimed.

`iris run` attempts automatic connection once on creation, but stays running
without a device or when selection fails. Later device operations or `iris claim`
can initiate a connection. It does not automatically re-claim a released device.
In a persistent session, `iris claim` can omit the target; `iris release` selects
the sole owned device, even offline, and `iris transfer start` can omit
`--device-id` while still requiring `--to-session`. Multiple verified transports
of one owned device count as one. Transfer retries use the original record's
identity. Reconcile commands and transfer record IDs remain explicit.

`recover` also attempts automatic ESP-Iris admission before ROM detection;
only an absent target allows the actual recovery to proceed to ROM selection.
An explicit `--hardware-mac` keeps the existing hardware identity workflow.
External `--gateway-profile` commands only select devices already connected
to that Gateway and never auto-acquire USB devices on the CLI host.

Reboots retain the current ownership; a new project session does
not inherit old connection history. `iris transfer start --device-id ...
--to-session ...` hands an idle device to a live receiving session. Interrupted
transfers retain a queryable `transfer_id`; use `status`,
`accept`, `abort`, or `reconcile` under `iris transfer` to
resolve them explicitly. Shared same-user SQLite records and OS locks coordinate
ownership without a global service. Legacy or remote Gateways do not participate.

## Command structure

```text
mosaico.py
├── doctor
├── project init
├── iris
│   ├── run / status
│   ├── list / claim / release / reconcile
│   ├── transfer start / status / accept / abort / reconcile
│   ├── logs / memory / crash / rpc
│   ├── app-update
│   ├── system-update
│   └── test enter-recovery / recovery-wifi / bridge-code
└── recover
```

`iris status` inspects the current project's Gateway without starting one or
installing a host environment. An absent Gateway returns
`{"running": false, "session": null}` with `--json`. It can also inspect a
temporary Gateway without taking ownership of its lifetime. Ownership commands
(`iris claim/release/reconcile` and `iris transfer ...`) require an existing
persistent session and fail immediately if none exists. Discovery (`iris list`)
and device operations may start temporary Gateways; creation/reuse, the selected
project and the Web URL are reported in text output and the run log.

`iris app-update` builds and installs a normal application. `iris system-update`
applies the images selected by a validated update bundle, which can also target
Recovery alone. `recover` restores the base firmware, including when ESP-Iris
is unreachable. `iris test` groups individual Recovery test operations:

| Command | Preconditions and result |
| --- | --- |
| `enter-recovery` | A reachable application restarts into retained Recovery; verify the same Device ID and a new Boot ID. If already in Recovery, return its current status. |
| `recovery-wifi` | Requires Recovery over USB; submit the SSID and password and wait for Wi-Fi connectivity. |
| `bridge-code` | Requires Recovery over USB, configured Bridge service and network connectivity; open the device's download page and return the pairing code, validity and website URL. |

Legacy command spellings remain accepted for existing scripts, but help and
examples use the structure above. For example, `install` maps to
`iris app-update`, `monitor` to `iris logs`, `init` to `project init`,
`session run/status` to `iris run/status`, and `device transfer-*` to
`iris transfer ...`. Existing operation identifiers and evidence formats remain
stable. `iris logs` follows by default (`--snapshot` prints retained logs only);
`iris memory --follow` enables continuous memory sampling.

The consuming repository owns a `.mosaico.json` file. All configured relative
paths are resolved from the directory containing that file. Recovery firmware
source and its reviewed bundle live under `firmware/recovery` and are resolved
from this checkout so the CLI and Recovery implementation are versioned
together. ESP-Iris is included alongside this project in the workspace, making
the workspace the single source of its device-side Iris implementation.

From a consuming workspace, prefer its root launcher:

```sh
python3 mosaico.py doctor
python3 mosaico.py iris app-update --project projects/app
python3 mosaico.py iris system-update --project projects/app
python3 mosaico.py iris test enter-recovery
```

For direct source-tree testing, pass the consuming workspace explicitly:

```sh
python3 /path/to/esp-mosaico-utils/esp-mosaico-recovery/mosaico.py \
  --workspace /path/to/firmware-workspace doctor
```

`iris app-update` updates only the application OTA partition. `iris system-update` builds
and submits the workspace's atomic application, UI assets, and system-data
bundle by default; use `--skip-build` or `--bundle PATH` to reuse artifacts.
`iris test enter-recovery` asks a reachable normal application to boot the retained
Recovery image without building or installing firmware. It waits for the same
Device ID to reconnect in Recovery with a new Boot ID; use `--device-id` when
more than one device is connected and `--timeout` to change the 30-second
transition limit. Both numeric Boot IDs and exact `boot_id_text` fields are
included in JSON output so 64-bit identities remain lossless for JavaScript
consumers.

The CLI searches the current directory and its parents for `.mosaico.json`.
Use `--workspace PATH` to select another workspace explicitly.

Create a normal application with `python mosaico.py project init my_app`. The consuming
workspace supplies a JSON template description through `workspace.init_template`;
there is no implicit template. Sources, file lists, text rules and resource paths
are maintained by that workspace. Output goes under `workspace.projects_dir`;
`default_project` is unchanged. The generic renderer handles path variables,
validated replacements, exclusive creation and failure cleanup without assuming
an application layout. See [the template format](docs/project-template.md).

Names use 1–31 ASCII letters, digits or underscores, starting with a letter,
and cannot be Windows reserved names. Existing destinations are rejected.
Use `--dry-run` to validate and list files without writing, or `--json` for stable
output. Initialization needs neither ESP-IDF nor a Gateway or connected device.

When multiple ESP32-S31 devices are already in ROM download mode, select the
target by its factory eFuse Base MAC. The CLI reads every registered ROM
endpoint without writing, repeats the MAC check immediately before flashing,
and verifies the same MAC in Recovery after re-enumeration:

```sh
python mosaico.py recover --hardware-mac 30:ed:a0:12:34:56 --source current
```

After upgrading from an older ESP-Iris release, the live Device ID changes once
from the NVS-stored random value to the deterministic hardware-derived value.
The Gateway retains the old ID and its operations as offline history; refresh
saved `--device-id` values with `python mosaico.py iris list`. Upgrade Recovery and
normal firmware together, since mixed versions use different identity schemes.
The pairing token and other retained NVS state are not erased.

Run the self-contained tool tests with:

```sh
python3 -m unittest discover -s tests -v
```


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
