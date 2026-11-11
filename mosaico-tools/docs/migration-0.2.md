# Migrating to mosaico-tools 0.2

Version 0.2 uses Gateway API major 2, Iris wire version 2 and
`esp-iris-system-update/0.2` bundles. Older devices, Gateways and bundles must be handled
in a separate legacy environment; there is no compatibility parser, protocol switching or automatic artifact conversion.

Host project sessions, device ownership and base-firmware validation records are isolated in the `esp-mosaico/0.2` state directory.
Ideas credentials and resume records also live there, so sign in again. The old directory remains unchanged and is not imported automatically.
The tools do not read, move or delete old validation records, or take over a still-running older Gateway.
Python dependency environments are separate from mutable device state; the old source-directory `.venv` is no longer reused.

Use `mosaico-tools/mosaico.py` in the tools directory or the corresponding workspace launcher.
The former `mosaico.py` in the Vibe Mode directory, its Python forwarding package and old build-script paths have been removed.
Integrate applications through the [public integration entry point](application-integration.md) and rebuild with the new test-partition contract.
Changing an old bundle's version string alone is insufficient.

Workspace `.mosaico.json` uses `schema_version: 2`; the old schema 1 is rejected immediately.
Recreate the configuration for the current paths. This repository's configuration has been explicitly updated; no runtime converter is provided.
The template descriptor schema is independent of the workspace schema. Templates with an unchanged format still use schema 1.

Update command paths in automation scripts; the old forms are no longer accepted:

| Old path | 0.2 path |
| --- | --- |
| `init` | `project init` |
| `install` | `iris app-update` |
| `system-update` | `iris system-update` |
| `list` | `iris list` |
| `monitor` | `iris logs` |
| `memory` / `crash` / `rpc` | `iris memory` / `iris crash` / `iris rpc` |
| `session run` / `session status` | `iris run` / `iris status` |
| `device claim` / `release` / `reconcile` | `iris claim` / `iris release` / `iris reconcile` |
| `enter-recovery` / `recovery-wifi` | `iris test enter-recovery` / `iris test recovery-wifi` |

Unchanged public commands such as `doctor` and `recover` remain available.

By default, use `iris system-update` to install a new project, layout or resources, and `iris app-update`
to update application code while keeping the complete partition table unchanged. Both require a separate high-speed USB or TCP data link.
With only UART or USB Serial/JTAG, logs, RPC, status and on-demand screenshots remain available, but firmware updates fail explicitly.
This restriction does not affect native `idf.py flash monitor` or base recovery through ROM.

Before writing a local project's System Update, the tools verify bundle and build-image hashes and archive BIN, ELF and
map files in the project Gateway for later crash decoding by the full ELF hash. An installation using only `--bundle`
has no project debug files and does not infer or borrow an ELF from another build.

For an explicit serial connection, use `iris run --endpoint PORT --baudrate 74880`. These parameters can also be supplied to
initial-connection commands such as `iris claim` and `iris device-status`.
The default baud rate is 115200 and should match the device's native console configuration. Explicitly specifying a USB Serial/JTAG
port authorizes connecting to that console; automatic discovery does not proactively open Serial/JTAG or generic UART bridges.
The live Device ID must still be verified after the handshake. Port paths and USB descriptions do not establish device identity.

If matching 0.2 base firmware is already installed, stop the owning Gateway and use the original monitor or native flashing tools directly.
For blank devices, devices fully flashed by third-party tools, or devices with an old layout, run recover first, then verify live identity,
mode and contract. See the Vibe Mode specification for migration erase/write scope and boot intent.

The repository's reviewed base bundle has been updated to 0.2.0 and is the default for ordinary `recover` and `app-update` operations.
Validate later source candidates with `recover --source current --source-path /path/to/firmware/vibe-mode`, then replace the reviewed bundle as a whole after acceptance.
For candidate-firmware code-update acceptance, use `iris app-update --recovery-source current --recovery-source-path /path/to/firmware/vibe-mode` to explicitly
validate version and compatibility against the candidate bundle generated above. This does not replace the reviewed directory or
fall back to another base bundle when the candidate is missing. Ordinary `app-update` still validates the reviewed bundle by default.
