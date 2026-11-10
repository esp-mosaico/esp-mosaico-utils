# ESP-Iris

[Main component guide](README.md)

ESP-Iris reduces unnecessary embedded build and flashing time, making device logs,
status and operation results easier for developers and AI Agents to understand, control and trace together. It turns
fragmented serial debugging into a unified, structured and recoverable development workflow.

ESP-Iris 0.2 adds commands and bounded printable API records to the standard ESP-IDF console.
`idf.py flash monitor` works without Gateway. UART and USB Serial/JTAG
use native IDF reset; S31 application USB uses the bundled Iris extension for ROM entry and port reenumeration tracking.
One worker serves the control link and optional separate data link carrying continuous media, files and firmware.
The device runs no
HTTP server, WebSocket server, JSON parser or framebuffer mirror, and performs no
media-sized allocations.

Multiple devices connect simultaneously through independent USB/TCP endpoints to one Python Developer
Gateway. Stable `device_id` values identify devices; Gateway aggregates and persists fleet events,
then distributes them to React Web Workbench, CLI clients and external Agents concurrently.

Use ESP-Iris when a product needs a browser engineering interface without embedding a web server or debug UI
in production firmware.

```text
ESP32 A -- USB CDC0 ---------\
ESP32 B -- USB Serial/JTAG ---+--> Python Gateway + persistence --+--> Web Workbench
ESP32 C -- TCP/Wi-Fi --------/                                   +--> CLI clients
ESP32 D -- TCP/Ethernet -----/                                   +--> External Agents
```

Each device has one Gateway owner; control and data sessions connect/disconnect independently.
Gateway and original monitor use the console exclusively without changing device modes.
One Gateway supervises multiple endpoints concurrently.
Workbench, CLI and Agent connections receive independent event streams; mutations are serialized per
device.

## Chip and transport support

The component declares ESP-IDF >=5.5 as a dependency minimum, not validation of every chip/SDK combination.
Package CI builds isolated projects for IDF 5.5 / H2 USB Serial/JTAG and a pinned IDF 6.2
development commit / S31 application USB. Source test projects add coverage with separately recorded validation scopes:

| Chip | Control link | Test project | Validation scope |
| --- | --- | --- | --- |
| ESP32-C2 | UART | `services_c2` | Build passed; existing control-link fixture passed hardware checks at 74880 baud |
| ESP32-H2 | USB Serial/JTAG | `services_h2` | Build passed; existing control-link fixture passed hardware checks |
| ESP32 | UART | `services_uart`, explicit target | Local build passed; no hardware validation in this round |
| ESP32-S31 | UART, USB Serial/JTAG, application USB, TCP | Existing baseline/system build groups | Prior validation retained; no device operations this round |
| Other SDK targets | UART; optional USB Serial/JTAG where supported | Not yet in build matrix | Unverified |

Initialize the pinned IDF at the repository root, then run `bash tools/ci/build_firmware.sh multichip`.
Use a separate build directory per target. The first three entries built successfully on 2026-10-16 with IDF commit
`7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe`; that local SDK also had camera-driver modifications.
Record remote CI and hardware validation separately; compilation cannot replace them.

C2/H2 hardware checks passed on 2026-10-16 through the consuming workspace's `mosaico.py`, using this branch's host
against already-installed `fc63d43-dirty` service fixtures without new flashing. Coverage included HELLO,
status/heap, binary RPC, control screenshots, logs, asynchronous jobs, 80 sustained RPCs per board, and
same-device/new-Boot-ID verification after software and hardware resets. The installed C2 firmware requires explicit 74880 baud.
Neither board's firmware enabled task-memory observation. File/continuous-media requests correctly rejected missing data links;
OTA and coredump decoding were not hardware-validated. Firmware identities and evidence hashes are in
[hardware validation records](test_apps/multichip-validation.json). This round also fixed missed restarts when serial ports did not reenumerate:
continuous HELLO probing detects them without repeating authentication for unchanged identities.


Additional same-day checks connected C2/H2 to one Gateway for 180 seconds with 377 RPCs per board;
each board restarted 3 times while the other kept responding. Unknown service/method, invalid arguments, recovery after RPC timeout,
64-log bursts, job cancellation and 3 release/reclaim cycles per board all passed. H2 automatic ROM identity reading
and return-to-application smoke tests passed without Flash writes. C2/H2 physical reconnect and user-confirmed full power-off cold boots also passed:
automatic reconnect retained identity, changed Boot ID and restored binary RPC.

The host consistently recognizes image chip IDs, requires image/device target equality on update and continues checking product,
board, layout and ABI after Recovery entry. Unknown IDs or missing targets never default to S31.
Coredump decoding selects target and Xtensa/RISC-V GDB from archived images, retaining explicit `ESP_IRIS_GDB` override.
UART ROM-download reset requires a known live target; ordinary running reset and USB Serial/JTAG reset
do not depend on HELLO identity.

UART and USB Serial/JTAG provide control links. Files, OTA, system writes and continuous media still require
enabled firmware services and a separately connected application USB or TCP data link. The application USB CDC driver and
ROM USB download extension remain S31-only; additional chip-ID recognition does not enable that driver. Other USB adapters,
IDF versions and board reset circuits require separate validation. Product layers still own Mosaico Recovery ABI/layout rules.

UART / USB Serial/JTAG also support native IDF `flash` /
`app-flash` wrapped by the local Gateway. Build the application first, then submit with `ctl flash --build-dir PATH --endpoint PORT`.
The caller supplies IDF/Python environments; `--idf-python` explicitly selects the interpreter.
Gateway pauses serial reads/reconnect while native tools use RTS/DTR to enter ROM, flash and reset.
Gateway then reopens serial, starts log reading and performs an additional running reset through the same handle,
resuming Iris handshake afterward. Capture covers the second boot; the application may have run briefly after the native-tool reset.
Ordinary reconnect does not reset. No separate data link or responsive old Iris application is required.
Console baud defaults to build configuration and may be overridden by `--baudrate`; flashing baud is independent.

Track progress with `ctl operation-watch OPERATION_ID` and logs with
`ctl logs --endpoint ENDPOINT --follow`, using the canonical endpoint identifier returned in
the operation result. Flashing results and Iris connection state are recorded separately;
successful flashing without an application connection is not reported as flashing failure. Additional reset results are stored in
`evidence.startup_reset`. Takeover/reset failure preserves successful-write results but cannot guarantee startup logs.
Exiting CLI does not stop an active writer; query the original operation before acting again.
ESP-Iris owns the generic flow. Consuming products use public `prepare_native_flash()`
to prepare requests and check product partition rules. Do not edit or rebuild the same directory concurrently with flashing.
Existing `recover` retains Vibe Mode-specific acceptance.

ESP32-H2 hardware checks passed on 2026-10-30 through the consuming workspace's `mosaico.py`:
both CP2102N UART and native USB Serial/JTAG passed native `flash`, repeated `app-flash`,
automatic log/RPC recovery and logging from ordinary non-Iris applications. USB Serial/JTAG
also passed 100 consecutive RPCs and result verification without another reset/write.
Firmware, operation IDs, data-preservation checks and evidence hashes are in
[native flashing records](test_apps/native-flash-validation.json).
After adding post-takeover reset, three rounds on each H2 link captured ROM headers, bootloader logs and
application `heartbeat=0`, with RPC recovery. Second-boot evidence is in
[startup-log records](test_apps/native-flash-startup-validation.json); original records retain earlier capture gaps.

## Included components

| Layer | Capabilities |
| --- | --- |
| Device component | One bounded worker, binary protocol, logs, status, RPC/Job, media, crash evidence, pairing and OTA |
| Developer Gateway | Concurrent USB/TCP endpoint supervision, fleet sessions, authentication, persistent operations, artifacts and REST/WebSocket APIs |
| Web Workbench | Device overview, logs, RPC, screen/input, media, firmware, operation history and settings |
| CLI client | Scriptable developer/Agent control with stable JSON output |

Defaults start only core links and log/status services. RPC tables, media buffers, pairing and OTA
are bounded by Kconfig and enabled only when configured or used.

## Environment and compatibility

| Scope | Requirement |
| --- | --- |
| ESP-IDF | 5.5 or newer |
| TCP | Default control port 19772 and data port 19773; application owns networking |
| Application USB | ESP32-S31; CDC0 text console and separate CDC1 data interface |
| USB Serial/JTAG | Retains standard console, hardware reset and JTAG; supports control services/on-demand screenshots |
| UART | Standard text console, RPC and screenshots; retains IDF console baud |
| Gateway | Python 3.8 or newer; current hardware validation primarily on Linux |
| Workbench | Building bundled React sources requires a current Node.js/npm environment |

Firmware may compile one or more transports. With multiple transports, physical connections negotiate within bounded windows;
a valid HELLO_ACK, authenticated for paired TCP, obtains ownership of the link role.
Control/data links verify the same device, boot and owner; data may connect first. Losing one link
does not close the other. Opening a port alone grants no ownership.

## Quick start

### 1. Add the component

Add to application `main/idf_component.yml`:

```yaml
dependencies:
  espressif/esp_iris: "^0.2.0"
```

Run `idf.py reconfigure` after adding/changing managed dependencies.
The component, Gateway and prebuilt Workbench reside in `managed_components/espressif__esp_iris`.
You may also follow [minimal Registry instructions](examples/minimal/README.md#from-the-component-registry)
to download the published example directly.

### 2. Select transports

Run `idf.py menuconfig` and open:

```text
Component config > ESP-Iris device link > Device transports
```

- **TCP** provides a printable console and separate authenticated data port.
- **USB** uses CDC0 for text/control and CDC1 for data. Configure
  `CONFIG_TINYUSB_CDC_COUNT=2`; interface descriptors identify roles.
  S31 may enable `CONFIG_ESP_IRIS_USB_AUTO_DOWNLOAD` to recognize download handshakes on CDC0.
  See [minimal USB flashing](examples/minimal/README.md#run-and-verify) for host-extension loading and initial installation.
- **USB Serial/JTAG / UART** retain native console/reset. Gateway, monitor and
  flashing tools use the same port exclusively. RPC, Jobs, input and on-demand screenshots work without data links.
- Products with an existing ESP-IDF REPL enable `CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT`
  and register `iris` through [esp_iris_console.h](include/esp_iris_console.h).
  The product retains input-driver ownership and configures a receive queue holding at least two complete protocol records.

Choose any compatible combination. Multiple transports use configurable candidate-handshake timeouts; when no
candidate is negotiating or active, `esp_iris_status_t` transport is `NONE`.

See the [example index](examples/README.md) for specific constraints.

### 3. Start ESP-Iris

```c
#include "esp_iris.h"

void app_main(void)
{
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_iris_boot_probe());
    /* Initialize product services after the early reset-attribution probe. */
    ESP_ERROR_CHECK(esp_iris_start());
}
```

This early idempotent probe records the running image before product initialization, covering later initialization crashes.
`esp_iris_start()` calls it as a fallback but cannot cover crashes occurring before
that call. Panic, watchdog and CPU lockup count toward crash loops by default; brownout and power glitches
do not unless explicitly configured. Counts clear after stable application runtime or a call to
`esp_iris_mark_healthy()`. `esp_iris_start()` is idempotent.
`esp_iris_stop()` releases worker, transports, VFS and
stdio ownership, allowing another start.

### USB application startup logs

With application USB and stdio capture, `CONFIG_ESP_IRIS_USB_EARLY_LOGS` is enabled by default.
Linker wrapping installs bounded stdout/stderr capture before `app_main()` while retaining
native console output. `esp_iris_start()` reuses those records and starts the existing USB driver without reinstalling
the USB stack or initializing application NVS early. Call it early in `app_main()` so USB
ports appear promptly.

`CONFIG_ESP_IRIS_USB_CONSOLE_HOST_WAIT_MS` defaults to 1500: after worker startup, wait up to
1.5 seconds for the host console to open, then return successfully and continue the app even on timeout. Set `0` to disable waiting.
Pending logs are bounded by `CONFIG_ESP_IRIS_LOG_RING_BYTES`, default 8192 bytes including record headers.
A full buffer evicts oldest records and reports dropped-byte counts before subsequent text.

USB enumeration alone does not consume startup logs. After CDC0 detects host control-line activity/input, a short
settling interval lets the terminal open, reset and flush input before text is sent. This supports original IDF Monitor's final
DTR-low state without an Iris handshake. Disconnect retains records still in the log ring;
bytes already handed to USB have no host acknowledgement/retransmission, so disconnects are not guaranteed lossless.
Gateway and ordinary monitor should take turns owning serial.

Coverage starts at `app_main()`, including stdout/stderr during Iris initialization. It excludes
ROM, bootloader, constructors, earlier system initialization and output bypassing stdio, which still need
an available native console. If another component wraps `app_main`, disable `CONFIG_ESP_IRIS_USB_EARLY_LOGS`;
capture then starts at `esp_iris_start()`. Calling stop before first start also releases early-installed capture.

### 4. Build firmware

```bash
idf.py build
```

Start with [`minimal`](examples/minimal/README.md) to validate TCP, USB CDC0
or USB Serial/JTAG before product integration.

### 5. Start Developer Gateway

After `idf.py reconfigure`, run from the application project directory:

```bash
ESP_IRIS_COMPONENT_DIR=managed_components/espressif__esp_iris
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r "$ESP_IRIS_COMPONENT_DIR/tools/requirements.lock"

python "$ESP_IRIS_COMPONENT_DIR/tools/esp_iris.py" web
```

For source checkouts, set this from the `esp-mosaico-utils` repository root:
`ESP_IRIS_COMPONENT_DIR=ESP-Iris/components/esp_iris`。
Use `web --demo` to explore Workbench without hardware.

The component package includes a built Workbench, requiring no Node.js at runtime.
Rebuild only after frontend source changes; see the [Gateway guide](tools/README.md#install-the-gateway).

One lockfile uses Python-version markers; pip selects validated dependencies for the active interpreter automatically.
Recreate the isolated environment when Python major/minor changes. Gateway runtime Python is independent of
the selected ESP-IDF version's requirement; the IDF tool environment still needs its required interpreter.

For Component Manager installations, set `ESP_IRIS_COMPONENT_DIR` to
`managed_components/espressif__esp_iris`. After Gateway starts, open
`http://127.0.0.1:8443/`。

Run a hardware-free demo:

```bash
python "$ESP_IRIS_COMPONENT_DIR/tools/esp_iris.py" web --demo
```

For USB/TCP selection, authentication, TLS, CLI, retention and development commands, see
the [Gateway and Workbench guide](tools/README.md).

## Features and resource behavior

| Feature | Default behavior | Device bound |
| --- | --- | --- |
| Links/status | Enabled | One worker and fixed protocol buffers |
| stdout/stderr logs | Enabled | `CONFIG_ESP_IRIS_LOG_RING_BYTES` |
| RPC handlers | Application-registered | `CONFIG_ESP_IRIS_MAX_RPC_HANDLERS` and `CONFIG_ESP_IRIS_RPC_BODY_BYTES` |
| Retained Jobs | Application-created | `CONFIG_ESP_IRIS_MAX_JOBS` |
| Screen/image/audio | Idle until host streaming starts | One `CONFIG_ESP_IRIS_MEDIA_LATEST_BYTES` buffer per active channel |
| Crash evidence | Read-only when present | `CONFIG_ESP_IRIS_CRASH_CHUNK_BYTES` chunks |
| TCP pairing | Disabled by default | One NVS token and challenge-HMAC state |
| OTA writer | Configurable; cross-project updates allowed by default | `CONFIG_ESP_IRIS_OTA_CHUNK_BYTES` chunks; `CONFIG_ESP_IRIS_OTA_REQUIRE_PROJECT_NAME_MATCH` can enforce the running project name |
| System Inventory | Enabled after product registers a read-only provider | Actual protected-region hashes and last commit result; no write callbacks |
| System Update | Enabled only after recovery registers a product backend | Signed manifests and bounded components/manifests/signatures/chunks; no generic raw-Flash API |
| File service | Enabled after logical-volume registration | One file task, one stream and `CONFIG_ESP_IRIS_FILE_CHUNK_BYTES` per chunk |

Media channels use credit and latest-chunk policies so slow hosts cannot create unbounded device queues.

Ordinary firmware with PSRAM XIP and external protocol buffers may use
`CONFIG_ESP_IRIS_USB_FIFO_PSRAM` (enabled by default when dependencies permit). Only CDC software-FIFO byte
storage moves to external BSS; capacity, USB endpoint DMA buffers, stream state and FreeRTOS lock placement remain unchanged.
Builds generate a source-hash-checked TinyUSB 0.21.0~2 adapter copy without modifying managed sources.
Unknown CDC source versions fail configuration explicitly, requiring adapter review or disabling the option. With external BSS,
`CONFIG_ESP_IRIS_SERVICE_STATE_PSRAM` also moves the fixed-size volume registry.
Writing firmware retains a separate internal-memory configuration.

`esp_iris_schedule_restart(delay_ms)` reuses the protocol task without creating tasks/timers.
Task/RPC callers select the boot target and record planned restart. Scheduling survives disconnects, waits for the current
service callback, and after the requested delay grants both TX queues up to 100 ms to drain. Explicit
`esp_iris_stop()` cancels it.


Before `esp_iris_start()`, register only directories explicitly approved for export by the product:

```c
ESP_ERROR_CHECK(esp_iris_file_volume_register(
    &(esp_iris_file_volume_config_t) {
        .id = "cfg",
        .base_path = "/littlefs/export",
        .capabilities = ESP_IRIS_FILE_VOLUME_READ |
                        ESP_IRIS_FILE_VOLUME_LIST |
                        ESP_IRIS_FILE_VOLUME_MTIME |
                        ESP_IRIS_FILE_VOLUME_WRITE |
                        ESP_IRIS_FILE_VOLUME_DELETE |
                        ESP_IRIS_FILE_VOLUME_MKDIR |
                        ESP_IRIS_FILE_VOLUME_RENAME |
                        ESP_IRIS_FILE_VOLUME_ATOMIC_REPLACE,
    }));
ESP_ERROR_CHECK(esp_iris_start());
```

Wire paths are always relative to registered roots. Gateway streams uploads/downloads without buffering entire files;
downloads support HTTP Range. Uploads create temporary files beside their targets and use strict
offset ACK, SHA-256, `fsync` and rename. Declare `ATOMIC_REPLACE` only if the underlying VFS actually supports
replacement semantics. Rename never overwrites existing targets; deletion accepts only files/empty directories, with no
recursive deletion or cross-volume operations.

## Security boundaries

- USB relies on physical access and performs no link pairing.
- Stable Device ID derives from factory eFuse Base MAC, independently of NVS. Raw TCP pairing
  defaults off; when enabled, tokens reside in the NVS partition selected by `CONFIG_ESP_IRIS_NVS_PARTITION_NAME`
  (default `nvs`). Links
  prove token possession through random challenges without transmitting the token itself.
- Gateway defaults to login-free loopback access; non-loopback clients need developer login or
  named Agent Tokens. File permissions are `files.read`, `files.write`
  and `files.delete`; new tokens default to `files.read` only.
- HTTP exposes credentials/device data to the local network and belongs only on trusted development networks;
  enable Gateway TLS elsewhere.
- Store Wi-Fi passwords, pairing tokens, TLS private keys and Agent Tokens in ignored local configuration
  or private files.
- Only reserved factory recovery should register both a read-only inventory provider
  and a System Update write backend. Ordinary firmware registers inventory only for post-restart verification.
  Gateway and device independently validate signed manifests. Product backends must pin trusted public keys, protect
  fixed system regions and verify each component. Inventory must hash complete protected regions from current Flash,
  including erased `0xff` padding, never return expected values saved in sysmeta.

## Discover TCP devices with mDNS

Products enabling TCP may initialize mDNS, set a hostname and publish DNS-SD
services:

```c
ESP_ERROR_CHECK(mdns_init());
ESP_ERROR_CHECK(mdns_hostname_set("my-product-a1b2c3"));
ESP_ERROR_CHECK(esp_iris_mdns_register(NULL));
```

This API publishes `_esp-iris._tcp.local.` with a unique
`ESP-Iris-<MAC-suffix>` instance name. ESP-Iris owns only that service; products should call
`esp_iris_mdns_unregister()` before `mdns_free()`. mDNS metadata supports local-link discovery, not authentication,
and never broadcasts pairing tokens.

## Examples

All public examples ship with the component under [`examples/`](examples/README.md).

| Example | Transport | Use case |
| --- | --- | --- |
| [`minimal`](examples/minimal/README.md) | TCP, USB CDC0 + CDC1, USB Serial/JTAG, or all three | Identity, lifecycle, status, logs and transport arbitration |
| [`tcp_wifi`](examples/tcp_wifi/README.md) | TCP | Application-managed Wi-Fi and DHCP |
| [`tcp_pairing`](examples/tcp_pairing/README.md) | TCP | Challenge-HMAC pairing and token configuration |
| [`rpc_jobs`](examples/rpc_jobs/README.md) | USB CDC0 + CDC1 | RPC handlers and cancelable Jobs |
| [`display_input`](examples/display_input/README.md) | USB CDC0 + CDC1 | Screenshots, mirroring and pointer input |
| [`media_streams`](examples/media_streams/README.md) | USB CDC0 + CDC1 | Synthetic image and PCM audio streams |
| [`file_transfer`](examples/file_transfer/README.md) | USB CDC0 + CDC1 | Streaming uploads/downloads and metadata operations |
| [`ota`](examples/ota/README.md) | USB CDC0 + CDC1 | Recovery-first/direct OTA, acceptance and rollback |
| [`file_service`](examples/file_service/README.md) | USB CDC0 + CDC1 | FATFS logical volumes and bounded file operations |
| [`crash_recovery`](examples/crash_recovery/README.md) | USB CDC0 + CDC1 | Retained Core Dumps and factory recovery after repeated crashes |
| [`lifecycle`](examples/lifecycle/README.md) | USB CDC0 + CDC1 | Stop, unregister, restart and reconnect |

Internal hardware fixtures remain in `test_apps/` and are excluded from release archives.

## Documentation

- [Public C API](include/esp_iris.h)
- [System Inventory provider API](include/esp_iris_system_inventory.h)
- [System Update backend API](include/esp_iris_system_update.h)
- [Protocol constants](include/esp_iris_protocol.h)
- [Wire protocol 0.2](protocol/spec.md)
- [0.1 → 0.2 migration guide](protocol/migration-0.2.md)
- [Golden vectors](protocol/golden_vectors.json)
- [Gateway and Workbench](tools/README.md)
- [Example index](examples/README.md)
- [Architecture](https://github.com/esp-mosaico/esp-mosaico-utils/blob/main/ESP-Iris/docs/esp-iris-architecture.md)
- [Changelog](CHANGELOG.md)

## Version and license

Current sources target `0.2.0`; use repository sources before publication. Device, Gateway and host
APIs must be upgraded together and are incompatible with 0.1. ESP-Iris uses the
[Apache-2.0](LICENSE) license.
