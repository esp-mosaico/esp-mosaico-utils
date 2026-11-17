# Compatibility and integration

ESP-Iris owns its transport, Gateway and Workbench. Applications own networking,
board pins, partition layouts, filesystems, services and update policy. No
Mosaico Tools, private product firmware or product BSP is needed to install or
validate this component.

## Supported configurations

| Configuration | Release validation |
| --- | --- |
| IDF 5.5, ESP32-H2, USB Serial/JTAG | Isolated minimal example and Registry installation |
| IDF 5.5, ESP32-C2, UART | Isolated minimal example |
| IDF 5.5, ESP32-S3, TCP | Isolated minimal example; networking remains application-owned |
| IDF 5.5, ESP32, disabled | Isolated component with `CONFIG_ESP_IRIS_ENABLE=n` |
| IDF 6.2 revision `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe`, ESP32-S31 | All packaged examples, application USB, Wi-Fi TCP, and a PSRAM FIFO build |

The manifest's `idf >=5.5` is the dependency floor. Other SDK/target combinations
are not covered by this matrix. S31 support requires an SDK supporting that chip;
it does not imply that S31 works with IDF 5.5. Build checks do not establish board
pin correctness or physical USB, reset, update and power-cycle behavior.

The S31 restart adapter binds to the SDK's restart translation unit and preserves
the SDK shutdown sequence. An SDK change to that integration point fails CMake
configuration explicitly and needs an adapter update before release.

USB FIFO PSRAM placement is optional. It requires PSRAM XIP, external BSS,
external wire buffers and a firmware configuration without Iris Flash writers.
The adapter accepts compatible CDC structure declarations and buffer references;
it does not pin a release number or source hash. A layout it cannot safely adapt
fails configuration. Set `CONFIG_ESP_IRIS_USB_FIFO_PSRAM=n` to retain upstream
internal FIFO storage. Dependency upgrades must pass the PSRAM release build.

## Dependency profiles

The default `ESP_IRIS_BUILD_PROFILE=full` supports menuconfig transport selection.
For applications needing a smaller dependency graph, pass the CMake cache option
before configuration, for example `idf.py -D ESP_IRIS_BUILD_PROFILE=uart build`.
Profiles are `full`, `usb`, `usj`, `uart`, `tcp` and `disabled`. The profile and
transport Kconfig settings must agree; `disabled` requires Iris disabled in
menuconfig. CMake dependencies are expanded before Kconfig, so changing only a
transport option does not prune dependencies from the default full profile.

## Public host integration

Use `iris_gateway.client` API major 1 for project coordination and passive
ownership snapshots. It depends only on the Python standard library. Live
operations use the Gateway HTTP/CLI APIs and their advertised capabilities.
Do not import private `link`, `ownership` or `store` implementations, read SQLite
tables, or infer compatibility from a monorepo commit or product version.

`LocalProject` owns canonical project keys, startup locks, connection records,
launch arguments and operation evidence. `registry_snapshot` checks same-user
session liveness. Registry reads do not migrate or recreate unknown schemas.
Source fingerprints describe the component's runtime files; a Git checkout is
not required. A source mismatch must not stop another client's running Gateway.

Product recovery contracts, expected firmware versions, partition hashes and
signature requirements are supplied through the public operation interfaces.
Standalone Iris has no dependency on a product Recovery implementation.

## Versions and upgrades

Component, bundled Gateway and Workbench versions move together. Iris versions
are independent of consuming firmware and tools. Wire protocol 0.2 and Gateway
HTTP API v2 are incompatible with 0.1; follow the packaged
[migration guide](../protocol/migration-0.2.md). Back up host state and credentials
before upgrading across a state schema boundary; downgrading executables alone
does not undo a state migration.

The Gateway supports Python 3.8 and newer with the dependency lock's version
markers. Its Python environment is separate from ESP-IDF. The component-root
launcher offers `setup` and `doctor`; existing `tools/esp_iris.py` integrations
continue to work. Physical-device validation is primarily on Linux; host tests
also cover Windows and macOS in the public CI matrix.
