# ESP-Iris

ESP-Iris is an ESP-IDF component for structured device development and
diagnostics. It adds bounded console records, RPC and job execution, logs,
status, media, files, crash evidence, pairing, and update services without
embedding an HTTP server or browser UI in product firmware.

A Python Developer Gateway owns device links, persists engineering records, and
serves the React Web Workbench, CLI clients, and external agents. One Gateway
can supervise multiple devices over USB, UART, USB Serial/JTAG, or TCP.

```text
ESP32 devices --> control/data links --> Developer Gateway --> Workbench
                                                       +--> CLI and agents
```

Device-changing operations are serialized per device. The Gateway and stock
IDF monitor take turns owning a console endpoint; no firmware mode switch is
required. Product applications continue to own networking, board pins,
filesystems, partition layouts, and update policy.

## Compatibility

The component manifest requires ESP-IDF 5.5 or newer. This is a dependency
floor, not validation of every target and transport combination.

| Target / SDK | Validated transport or profile |
| --- | --- |
| ESP32-H2 / IDF 5.5 | USB Serial/JTAG |
| ESP32-C2 / IDF 5.5 | UART |
| ESP32-S3 / IDF 5.5 | TCP |
| ESP32 / IDF 5.5 | Disabled component profile |
| ESP32-S31 / pinned IDF 6.2 revision | UART, USB Serial/JTAG, application USB, and TCP |

UART and USB Serial/JTAG provide the control link. Files, OTA, System Update,
and continuous media require a separately connected application USB or TCP
data link and the corresponding firmware service. Application USB and its ROM
download extension are currently S31-specific.

See [Compatibility and integration](docs/compatibility.md) for build profiles,
release validation, dependency boundaries, and upgrade rules.

## Install

Add the component to the application's `main/idf_component.yml`:

```yaml
dependencies:
  espressif/esp_iris: "^0.2.0"
```

Run `idf.py reconfigure` after changing managed dependencies. Component Manager
installs the component, Gateway, Workbench distribution, examples, and public
documentation under `managed_components/espressif__esp_iris`.

## Select transports

Open `idf.py menuconfig` and select:

```text
Component config > ESP-Iris device link > Device transports
```

| Transport | Use |
| --- | --- |
| UART | Native console, reset, RPC, jobs, logs, and bounded snapshots |
| USB Serial/JTAG | Native console/reset/JTAG with the same control services |
| Application USB | CDC0 text/control plus CDC1 binary data on ESP32-S31 |
| TCP | Application-owned network with separate control and data ports |

Applications with an existing ESP-IDF REPL can enable
`CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT` and register the `iris` namespace
through [esp_iris_console.h](include/esp_iris_console.h).

## Minimal startup

Start Iris early enough to retain initialization failures:

```c
#include "esp_iris.h"

void app_main(void)
{
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_iris_boot_probe());
    /* Initialize product services after reset attribution. */
    ESP_ERROR_CHECK(esp_iris_start());
}
```

`esp_iris_boot_probe()` is idempotent and records reset attribution before later
product initialization can fail. `esp_iris_start()` is also idempotent and
starts only the transports and services enabled by Kconfig or registered by the
application. `esp_iris_stop()` releases transport, worker, VFS, and stdio
ownership so the component can be started again.

Build normally:

```bash
idf.py build
```

Use the packaged [minimal example](examples/minimal/README.md) to verify one
transport before integrating product services. The
[example index](examples/README.md) covers TCP networking and pairing, RPC/jobs,
display input, media, files, OTA, crash recovery, and lifecycle behavior.

## Start the Developer Gateway

Set the component directory for a source checkout or managed installation:

```bash
# Source checkout
ESP_IRIS_COMPONENT_DIR=ESP-Iris/components/esp_iris

# Managed component
# ESP_IRIS_COMPONENT_DIR=managed_components/espressif__esp_iris
```

The component-root launcher creates an isolated Python environment without
modifying ESP-IDF's Python installation:

```bash
python "$ESP_IRIS_COMPONENT_DIR/esp_iris.py" setup
python "$ESP_IRIS_COMPONENT_DIR/esp_iris.py" doctor
python "$ESP_IRIS_COMPONENT_DIR/esp_iris.py" web
```

Open `http://127.0.0.1:8443/`. To evaluate the Workbench without hardware:

```bash
python "$ESP_IRIS_COMPONENT_DIR/esp_iris.py" web --demo
```

The [Gateway and Workbench guide](tools/README.md) documents discovery,
endpoint selection, native flashing, authentication, TLS, CLI commands,
operations, storage, and troubleshooting.

## Integration topics

- Application USB startup logging and SDK profiles: [compatibility](docs/compatibility.md)
- Public device API, mDNS, and file-volume registration: [esp_iris.h](include/esp_iris.h)
- Console integration: [esp_iris_console.h](include/esp_iris_console.h)
- Wire security and service contracts: [protocol specification](protocol/spec.md)
- TCP discovery example: [tcp_wifi](examples/tcp_wifi/README.md)
- File-volume example: [file_service](examples/file_service/README.md)
- Host ownership and security: [Gateway guide](tools/README.md#access-and-authentication)

## Documentation

- [Compatibility and integration](docs/compatibility.md)
- [Public C API](include/esp_iris.h)
- [Protocol specification](protocol/spec.md)
- [0.1 to 0.2 migration](protocol/migration-0.2.md)
- [Developer Gateway and Web Workbench](tools/README.md)
- [Examples](examples/README.md)
- [Changelog](CHANGELOG.md)

## Version and license

This source tree targets ESP-Iris `0.2.0`. Device protocol and Gateway API 0.2
are incompatible with 0.1 and must be upgraded together. ESP-Iris is licensed
under [Apache-2.0](LICENSE).
