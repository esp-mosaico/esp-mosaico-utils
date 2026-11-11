# ESP-Mosaico Tools

The [0.2 software specification](docs/mosaico-tools-software-spec-zh.md)
and [migration guide](docs/migration-0.2.md) describe the breaking release.
The source uses Gateway API 2 and the new test-partition product contract.
Default updates validate the published Recovery bundle in `../firmware/recovery/`;
the GitLab source checkout does not include generated images.
Old devices and old bundles require their separate 0.1 environment.

Workspace-consumed command-line tools for ESP-Mosaico development and device
operations. A firmware workspace pins the containing `esp-mosaico-utils`
repository; the CLI package does not need to be installed into the user's
Python environment.
Shared GSP acquisition and Ideas resource generation live in
[shared/](../shared/README.md); application version pins remain owned by tools.

The user-facing retained firmware is **Vibe Mode** (`firmware_mode=recovery`).
**ROM Download Mode** runs the chip download program without ESP-Iris.
`iris test enter-recovery` enters Vibe Mode; `recover` writes base firmware.
See [application integration](docs/application-integration.md).

Vibe builds with UART maintenance support retain USB High-Speed and can retry
the installed application without a screen or application USB cable:

```sh
python mosaico.py iris run-app --endpoint /dev/ttyUSB0 --baudrate 115200
python mosaico.py iris app-flash --endpoint /dev/ttyUSB0 --baudrate 115200 --run-app
```

Run these from the consuming application's workspace. Vibe defaults to UART0,
TX GPIO58 / RX GPIO59 at 115200 baud; both firmware images and the host must use
the connected pins and matching baud rate. `--run-app` also works with `iris flash`.
It is opt-in: normal native flashing keeps its existing behavior. If the
application is already running after flashing, no additional restart is sent.
Otherwise the command uses Vibe product RPC `0x1202/8` to verify/select `ota_0`,
reset the crash-loop quarantine and restart. It verifies the same device's new
Boot ID and selected ELF SHA through Iris. An acknowledgement timeout or a
return to Vibe never triggers an automatic retry. Applications without Iris
cannot provide this reconnection verification.

This requires updating the retained Vibe image with UART support first; an
application's UART configuration cannot enable it in an older Vibe image.
Current-source builds do not replace the reviewed recovery bundle. The UART
control entry does not carry bulk updates: native UART flashing still uses
ROM Download Mode, while USB CDC1 / TCP retain Iris bulk transfer support.

Local Gateways are shared project services. Device commands start or reuse one
and retain a renewable client lease for their duration. Every
`python mosaico.py iris run --project <application>` retains an independent
foreground client, including when the Gateway already exists. Ctrl-C releases
only that client. The printed URL opens the Web workbench, whose event connection
also retains a client. With no clients and no active work, the Gateway exits after
**10 idle seconds**. The original launching command does not own its lifetime.
CLI clients renew every 5 seconds and expire after 20 seconds without renewal;
client expiry is separate from the subsequent idle countdown. There is no stop
command and the workbench cannot wake an exited Gateway.

`iris list` and `iris status` do not open unclaimed devices. Device operations can
omit their target: prefer the sole connected device, then the sole existing
ownership (wait for that identity if offline), then the sole available USB
device from live enumeration. Multiple candidates report a selection error.
Unconnected TCP/mDNS endpoints, cached history, ROM and Serial/JTAG interfaces
are not automatic USB candidates. Explicit targets never fall back to another
device, and reservations held by other sessions are never automatically reclaimed.

`iris run` attempts automatic connection once on creation, but stays running
without a device or when selection fails. Later device operations or `iris claim`
can initiate a connection. It does not automatically re-claim a released device.
In a shared session, `iris claim` can omit the target; `iris release` selects
the sole owned device, even offline. Multiple verified transports of one device
count as one. `iris takeover start` requires an explicit device ID or endpoint.
Use the original `--takeover-id` when retrying.

`recover` also attempts automatic ESP-Iris admission before ROM detection;
only an absent target allows the actual recovery to proceed to ROM selection.
An explicit `--hardware-mac` keeps the existing hardware identity workflow.
External `--gateway-profile` commands only select devices already connected
to that Gateway and never auto-acquire USB devices on the CLI host.

Reboots retain the current ownership; a new project session does not inherit old
connection history. Device handoff is initiated only by the receiving project
through `iris takeover start`. Shared same-user SQLite records and OS locks
coordinate ownership without a global service.
## Command structure

```text
mosaico.py
├── doctor
├── project init
├── iris
│   ├── run / status
│   ├── list / claim / release / reconcile
│   ├── takeover start / status / resume / abort / reconcile
│   ├── logs / memory / crash / rpc
│   ├── device-status / screenshot / operation-status
│   ├── app-update
│   ├── system-update
│   └── test enter-recovery / recovery-wifi
└── recover
```

`iris status` passively inspects the selected project, including clients,
keepalive reasons, and the idle countdown. `iris status --all` reads the shared
same-user registry and probes live local Gateways across workspaces, even if this
project has no Gateway. Neither query starts a Gateway, prepares a host runtime,
or retains a client. An absent Gateway returns
`{"running": false, "session": null}` with `--json`; orphaned ownership is
reported separately. `--all` and `--project` are mutually exclusive.

For live device evidence, use `iris device-status --json`; it verifies Device ID,
Boot ID and `stale=false` through the selected project's Gateway. Unlike host
`iris status`, this command can acquire the project's device and query it live.
Add `--inventory` to include live bootloader and partition-table hashes; the
command rejects evidence if the device reboots during the read.
Use `iris screenshot device.png --json` to save the device image directly, with
image metadata, operation ID and the verified device/boot identity. A reboot during
capture fails verification. Inspect the saved image itself rather than a screenshot
of the Web workbench. `iris operation-status <operation-id> --json` reads an existing
record without acquiring a device or replaying the operation; it may start/reuse the
project Gateway. A successful query preserves failed or unknown operation outcomes
in `operation.status`. Share the workbench URL for developer observation; browser
automation and CLI/Web comparisons are for workbench testing or explicit user requests.

Ownership mutations (`iris claim/release/reconcile` and takeover actions) can
start/join shared Gateways. Takeover status remains passive. A device claim is
not a keepalive: use `iris run` when its ownership must persist across commands.
Active takeover requests hold the receiver until validation completes. Interrupted
takeover reservations remain protected and require explicit
reconciliation; they are never silently released to another project.

Gateways must provide the 0.2 API and shared-lifetime capability. The 0.2
ownership database and private state are isolated from earlier installations;
stop old Gateways through their original tools before migrating. Remote
profiles keep their externally managed lifetimes.

`iris app-update` installs code-only changes with an identical device partition table.
Prefer `iris system-update` for a new application, layout change, or changed resources. It
applies the images selected by a validated update bundle, which can also target
Vibe Mode alone. `recover` restores the base firmware, including when ESP-Iris
is unreachable. `iris test` groups individual Vibe Mode test operations:

| Command | Preconditions and result |
| --- | --- |
| `enter-recovery` | A reachable application restarts into Vibe Mode; verify the same Device ID and a new Boot ID. If already in Vibe Mode, return its current status. |
| `recovery-wifi` | Requires Vibe Mode over USB; submit the SSID and password and wait for Wi-Fi connectivity. |

> [!TIP]
> Bridge push-based downloads and `iris test bridge-code` have been removed.
> Use the six-digit application ID on the device download page to pull Ideas.

Only the public command paths above are accepted. Replace old script commands
using the [0.2 migration table](docs/migration-0.2.md); there are no compatibility
aliases. `iris logs` follows by default (`--snapshot` prints retained logs only);
`iris memory --follow` enables continuous memory sampling.

The consuming repository owns a `.mosaico.json` file with `schema_version: 2`.
All configured relative
paths are resolved from the directory containing that file. The reviewed bundle
lives in `../firmware/recovery/`; `recover --source reviewed` uses the public
`recovery/` staging project and needs no private source checkout. Building a
candidate requires `recover --source current --source-path PATH`. Candidate-based
app validation requires `iris app-update --recovery-source current --recovery-source-path PATH`.
These explicit source paths are relative to the calling shell and must point to
the firmware project itself; they are rejected with the reviewed source. The
prepared candidate is read from `PATH/build-mosaico-vibe-mode/recovery-current/`.

From a consuming workspace, prefer its root launcher:

```sh
python3 mosaico.py doctor
python3 mosaico.py iris app-update --project projects/app
python3 mosaico.py iris system-update --project projects/app
python3 mosaico.py iris test enter-recovery
```

For direct source-tree testing, pass the consuming workspace explicitly:

```sh
python3 /path/to/esp-mosaico-utils/mosaico-tools/mosaico.py \
  --workspace /path/to/firmware-workspace doctor
```

`iris app-update` updates only the application OTA partition. `iris system-update` builds
and submits the workspace's atomic application, partition table, and declared resource
bundle by default; use `--skip-build` or `--bundle PATH` to reuse artifacts.
When only a control link is connected, local System Update waits up to five
seconds for its data link to complete its identity handshake before submission.
A missing data link or a changed Boot ID ends preparation with a diagnostic.
`iris test enter-recovery` asks a reachable normal application to boot the retained
Vibe Mode firmware without building or installing firmware. It waits for the same
Device ID to reconnect in Vibe Mode with a new Boot ID; use `--device-id` when
more than one device is connected and `--timeout` to change the 30-second
transition limit. Both numeric Boot IDs and exact `boot_id_text` fields are
included in JSON output so 64-bit identities remain lossless for JavaScript
consumers.

The CLI searches the current directory and its parents for `.mosaico.json`.
Use `--workspace PATH` to select another workspace explicitly.

Create a normal application with `python mosaico.py project init my_app`. The consuming
workspace supplies a JSON template description through `workspace.init_template`;
there is no implicit template. Sources, file lists, text rules and resource paths
are maintained by that workspace. The creator supplements missing Git and quality
configuration and initializes an independent Git repository on branch `main`.
The same setup applies to `game create/new`, including Engine examples. Existing
template configuration takes precedence; preserved filenames are reported.
Output goes under `workspace.projects_dir`;
`default_project` is unchanged. The generic renderer handles path variables,
validated replacements, exclusive creation and failure cleanup without assuming
an application layout. See [the template format](docs/project-template.md).

Names use 1–31 ASCII letters, digits or underscores, starting with a letter,
and cannot be Windows reserved names. Existing destinations are rejected.
Use `--dry-run` to validate and list files without writing, or `--json` for stable
output. Initialization requires Git 2.28+ but needs neither ESP-IDF nor a Gateway
or connected device. It does not stage files, create a commit, configure a remote
or install hooks. Enable the pinned checks from the new project directory using
the commands printed by creation; see its `tools/quality/README.md` for first-run
staging, formatting fixes and manual C/C++ analysis. The default checks cover
text, ESP-IDF AStyle formatting, Ruff, configuration syntax, secrets, artifacts,
file permissions and project component conventions. The Mosaico hooks call the
shared checker in this utils checkout through relative paths; pin the workspace's
utils revision alongside other dependencies. Only configuration and policy are
copied into the project. See [template ownership](templates/README.md) for the
separation between application templates, shared defaults and executable tools.

When multiple ESP32-S31 devices are already in ROM download mode, select the
target by its factory eFuse Base MAC. The CLI reads every registered ROM
endpoint without writing, repeats the MAC check immediately before flashing,
and verifies the same MAC in Vibe Mode after re-enumeration:

```sh
python mosaico.py recover --hardware-mac 30:ed:a0:12:34:56 --source current --source-path /path/to/firmware/vibe-mode
```

After upgrading from an older ESP-Iris release, the live Device ID changes once
from the NVS-stored random value to the deterministic hardware-derived value.
The Gateway retains the old ID and its operations as offline history; refresh
saved `--device-id` values with `python mosaico.py iris list`. Upgrade Vibe Mode and
normal firmware together, since mixed versions use different identity schemes.
The pairing token and other retained NVS state are not erased.

Run the self-contained tool tests with:

```sh
python3 -m pytest -q tests
```



Local System Update bundles are inspected before device admission; the CLI records
each image's offset, size, and hash. `app-update` layout mismatches return
`partition_layout_mismatch`, both table hashes, and a product system-update command.
The command never rewrites a project's layout or silently expands OTA write scope.

Built normal applications must declare the product role/board/layout/Recovery ABI
in effective `build/config/sdkconfig.json`, including when reusing artifacts.
Both update paths require Gateway capability `update-acceptance/v1` and validate
the final role and product contract after the healthy boot and image identity checks.
Device ID selection can verify multiple candidates; an explicit endpoint is strict,
and failed new probes release their endpoint/device reservations.

### ROM recovery operations

`mosaico.py recover` prepares its bundle before submitting a single local Gateway
operation for ROM flashing and Vibe Mode verification. ROM identity probes use
the same process-owned endpoint locks. The operation ID, raw executor output and
verification evidence are retained; there are no maintenance leases or renewals.
A wait timeout leaves the running writer protected. Inspect its operation ID
before retrying. A completed failed operation does not retain a permanent device
reservation. The CLI and Workbench expose offline, connecting, idle, busy and
needs-recovery states independently of project ownership and firmware mode.

To request an owned device from a newly started project Gateway:

```sh
python mosaico.py iris takeover start --project projects/my_app --endpoint /dev/ttyACM0
python mosaico.py iris takeover start --project projects/my_app --device-id <DEVICE_ID> --force --timeout 120
```

The default requires an idle device. `--force` stops admission of new work and
cancels queued operations, waits for active writes, then stops mirrors and
cooperatively cancels background Jobs. Timeout keeps the original owner and does
not kill writes. A log monitor or `iris run` client alone never blocks handoff.
Keep the reported takeover ID when querying or retrying an interrupted request:

```sh
python mosaico.py iris takeover status --project projects/my_app --takeover-id <ID>
python mosaico.py iris takeover resume --project projects/my_app --takeover-id <ID>
```

`resume` continues validation in the original receiving session. If no reservation
was created, retry `start` with the original ID. `abort` runs in the original
owning project; it never rolls back a completed takeover or reclaims an accepting
live receiver. `reconcile` is available to a participant project only after both
original sessions have exited and physical locks are free. All four record
commands require `--takeover-id`; `status` never starts a Gateway.

## Publish a Mosaico Ideas file collection

The [file release protocol](docs/ideas-file-release/README.md) uses one immutable
ZIP upload and direct device manifest GET requests. The CLI, local integration
server and Vibe Mode implement the new format only. An upload creates a **draft**;
publication is separate. Ordinary Ideas cannot contain Vibe Mode or bootloader
components. Vibe Mode self-update remains outside this protocol.

Install host-only dependencies with `python3 -m pip install -r mosaico-tools/requirements-ideas.txt`.
Display generation also needs the platform's FreeType/libraqm runtime. Device
resources are generated before the ZIP is frozen; uploading never rebuilds them.

Before packaging for upload, fetch the public category list from the selected server
with `curl --fail --silent --show-error "https://mosaico.ai/api/v1/categories?group=software"`
(use `group=hardware` for hardware projects). Choose a category by `name`/`name_en`
and put its integer `id` in `project.category_id`. Replace the illustrative `123`
below with that returned ID; IDs depend on the server and must not be guessed.

Keep this author configuration in the application's `mosaico-ideas.json`:

```json
{
  "schema": "mosaico-ideas/project-release/1",
  "project": {"title": "Bilingual demo", "content_type": "software", "category_id": 123},
  "firmware": "build/demo-system-update.irisfw",
  "website": {"readme": "website/readme.md", "covers": ["website/cover.png"]},
  "device": {
    "default_locale": "zh-CN",
    "presentations": {
      "zh-CN": {"name": "双语示例", "description": "下载后可离线切换语言。", "font": "assets/NotoSansCJK-Regular.ttc", "icon": "assets/icon.png"},
      "en": {"name": "Bilingual demo", "description": "Switch languages offline after downloading.", "font": "assets/NotoSansCJK-Regular.ttc", "icon": "assets/icon.png"}
    }
  }
}
```

Each locale defaults to `mode: "generate"`; alternatively use only
`{"mode":"prebuilt","display":"device/en/display.json"}` with adjacent font/icon
files. Mixing generated and prebuilt fields in one locale is rejected. See the
[author schema](mosaico-ideas.schema.json) for fields and limits. Website paths
remain relative; referenced images must be listed in `resources` or `covers`.

```sh
# First use the application's offline ESP-IDF build to generate its
# system-update-bundle target; package an existing .irisfw below.
python mosaico.py project package --project projects/demo --output dist/release.zip
python mosaico.py project validate dist/release.zip --json
python mosaico.py account login
python mosaico.py project upload dist/release.zip --create --yes --json
# Replace an unsubmitted draft using the cloud project public_id.
python mosaico.py project upload dist/release.zip --update PUBLIC_ID --yes --json
```

`project package --bundle PATH` overrides the configured firmware input. Packaging
is offline and deterministic. Both packaging and upload validate ZIP structure,
all hashes, the Iris firmware/product layout, actual image encoding, MIFF glyphs,
and complete Chinese/English dependency sets. They reject extra or missing files,
links, traversal, ambiguous paths, animations and unsupported firmware components.

Uploads use synchronous Agent API POST/PATCH requests with a single `release`
file. A successful response returns `public_id` and `status: draft`; a six-digit
app number is not required. Cloud publication owns app IDs, app numbers and
published-version uniqueness. No draft version or asynchronous receipt is needed.
Every explicit upload sends a request; writes are not automatically retried.
If a response is lost, check the website before creating another project.
`--server` chooses the API origin; `--ca-file` trusts a private test CA.
The CLI requires `project.category_id` before upload, although the release schema
keeps it optional for offline packaging and validation. The server checks that the
category exists, is enabled and belongs to `content_type` (default `software`).
For `invalid_category`, fetch the list again, correct the author configuration and
repackage. PATCH replaces all metadata, so include the category on updates too.
The category stays inside the ZIP; the multipart request still has only `release`.

Provide bilingual descriptions and an icon when practical. A generated description
may be omitted or empty, and an icon may be omitted; supplied assets must still
pass format and size checks. Names, fonts and both locales remain required.
Do not supply `categories` or `license` in author configuration or the upload manifest.
See the [OpenAPI contract](docs/ideas-file-release/api.openapi.yaml) and
[integration checks](docs/ideas-file-release/testing.md) for server requirements.

For a runnable server, TLS setup, explicit test publication and device acceptance,
see [local integration testing](docs/ideas-file-release/testing.md).

```sh
python3 -m pytest mosaico-tools/tests
python3 -m pytest mosaico-tools/tests
```

Streaming build commands write complete stdout/stderr bytes to a unique
`stdout-*.log` in the command's run directory; `raw.log` points to this file and
records progress. `RunContext.run(..., output_status=...)` returns at most the
last 64 KiB in `CompletedProcess.stdout`, with `stdout_path`,
`stdout_truncated` and `progress_dropped` metadata. Checked-command and timeout
exceptions carry the same bounded diagnostic output and file path. Progress
notifications use a bounded queue and may skip old lines under load; long lines
are split into 16 KiB character chunks. Sensitive output is never spooled or
forwarded to progress callbacks. Non-streaming structured command responses
retain their existing stdout contract.
