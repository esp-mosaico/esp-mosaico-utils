<a id="给已有应用添加-recovery-和-iris-日志"></a>

# Adding Vibe Mode and Iris logs to an existing application

Vibe Mode is reserved firmware running ESP-Iris, distinct from the chip's ROM download mode.
See the [application integration guide](../mosaico-tools/docs/application-integration.md) for technical names and public APIs.

Migration can be incremental: **first update the partition table and add the Vibe Mode image; integrate
Iris later if application logs are needed.** Keep the existing project directory, application code, UI framework and build process; no preliminary conversion to an example project is required.

<a id="第一部分只添加-recovery"></a>

## Part one: Add Vibe Mode only

### 1. Reserve the first 2 MiB in the partition table

Reserve Flash `[0x000000, 0x200000)` for Vibe Mode and its system data. The following system partitions match this repository's
[prebuilt Vibe Mode](../firmware/recovery/manifest.json)
and can be merged into an existing `partitions.csv`:

```csv
# Name,    Type, SubType, Offset,   Size,     Flags
otadata,   data, ota,     0x9000,   0x2000,
phy_init,  data, phy,     0xb000,   0x1000,
sysmeta,   data, nvs,     0xc000,   0x14000,
factory,   app,  factory, 0x20000,  0x1c0000,
coredump,  data, coredump,0x1e0000, 0x20000,
```

The Vibe Mode image occupies `factory`, a 1.75 MiB slot. Earlier space contains the bootloader,
partition table and system data. The current prebuilt bundle targets ESP-Mosaico / ESP32-S31 with 16 MiB Flash.

**Arrange space after `0x200000` as the application needs; do not copy an example's entire layout.** Existing application,
NVS, filesystem and UI-resource partitions can retain their sizes and labels, adjusting only conflicting addresses.
If the original application occupies `factory`, move it to an OTA application partition and reserve `factory` for Vibe Mode.

Check these three requirements:

- Partitions must not overlap or exceed Flash capacity; application offsets align to 64 KiB and data offsets to 4 KiB.
- Current Vibe Mode startup requires initializable `nvs` and `sysmeta`. Retain `nvs`; do not add only a
  `factory` entry while removing other required data partitions.
- Moving NVS/filesystem offsets does not move their data automatically. Back up data to retain, then restore it at the new addresses.
  Partitions with unchanged addresses, sizes and formats that are not overwritten can remain untouched.

This prefix matches the existing prebuilt firmware; it does not standardize every application's partitions.
Simply booting Vibe Mode differs from using complete System Update support: the latter currently checks fixed parameters for five
system partitions. Changing those parameters also requires changes to the Vibe Mode update implementation.

<a id="2-把-recovery-加入工程的安装镜像清单"></a>

### 2. Add Vibe Mode to the project's installation image list

Keep the original application build, add Vibe Mode to its installation list and use **your project's new partition table**:

| Image | Write location |
| --- | --- |
| New partition table `partition-table.bin` | `0x8000` |
| Prebuilt Vibe Mode `factory.bin` | `0x20000` |
| Original application and resource images | Their target addresses in the new partition table |

Also establish the boot entry point: the bootloader must select `factory` and the application using the new partition table.
For this repository's AI-button (GPIO7) entry into Vibe Mode, use the matching bootloader
at `0x2000`; otherwise verify that the existing bootloader has an equivalent entry point. Initial `otadata` controls
boot selection. Prebuilt `ota_data_initial.bin` boots Vibe Mode first and should not be unconditionally rewritten
during routine updates.

This is an image-integration list, not a requirement to integrate Iris into application firmware first. Actual device writes use the consuming workspace's
`mosaico.py`. Current `mosaico.py recover` writes the **complete base bundle**, including its
base partition table. It has no "add only Vibe Mode while retaining a custom partition table" option. Integrate the custom image list above
into that workspace's installation flow; `recover` cannot directly
replace it. Devices already running compatible Vibe Mode can skip this step.

<a id="3-确认原应用和-recovery-都能启动"></a>

### 3. Confirm both the original application and Vibe Mode boot

Verify Vibe Mode entry, expected application boot and normal access to original NVS, files and resources.
If Vibe Mode alone is needed, stop here. Application entry-point changes, Iris dependencies and
product identity fields are not required.

## Part two: Optionally add Iris logs to application firmware

### 1. Add the Iris component

Append the component directory before ESP-IDF's `project.cmake` include in the original `CMakeLists.txt`.
Replace the example path with the project's actual utils checkout and retain other build logic:

```cmake
set(MOSAICO_UTILS_ROOT "/path/to/esp-mosaico-utils")
list(APPEND EXTRA_COMPONENT_DIRS
    "${MOSAICO_UTILS_ROOT}/ESP-Iris/components/esp_iris")
```

Append `REQUIRES esp_iris` to `idf_component_register()` in the component using Iris.
If it already lists dependencies, append to that list. Do not bring in a second Iris copy from another source.

### 2. Select a transport

The example uses ESP32-S31 USB CDC0. Merge these settings into the existing `sdkconfig.defaults`:

```ini
CONFIG_ESP_IRIS_ENABLE=y
CONFIG_ESP_IRIS_TRANSPORT_USB=y
# CONFIG_ESP_IRIS_TRANSPORT_TCP is not set
# CONFIG_ESP_IRIS_TRANSPORT_USB_SERIAL_JTAG is not set
# CONFIG_BSP_USB_CONSOLE is not set
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
CONFIG_ESP_CONSOLE_SECONDARY_NONE=y
# CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG is not set
# CONFIG_ESP_IRIS_OTA is not set
```

Iris exclusively owns TinyUSB CDC0; the application must not initialize the same USB controller again. Log integration does not require
an application OTA writer, so it is disabled here. Existing `sdkconfig` overrides defaults; after editing,
confirm effective settings with `menuconfig` and rebuild. Retain the project's board-level Flash/PSRAM configuration.

Iris stores state in existing `nvs` by default. To share pairing and crash state with Vibe Mode,
set `CONFIG_ESP_IRIS_NVS_PARTITION_NAME="sysmeta"`. For TCP and other transports, see the
[Iris quick start](../ESP-Iris/components/esp_iris/README_zh.md).

### 3. Start Iris before application initialization

```c
#include "esp_iris.h"
#include "esp_log.h"

void app_main(void)
{
    ESP_ERROR_CHECK(esp_iris_start());
    ESP_LOGI("app", "Iris logging ready");

    /* Existing application initialization and task creation. */
}
```

Ordinary `ESP_LOGx` and `stdout/stderr` output is visible through Iris. Existing custom log backends
or direct UART writes need separate integration. Pre-startup and ROM/bootloader logs are not replayed automatically, and logs
may be dropped when buffers fill. Log-only integration needs no Vibe Mode adapter component, product identity declaration or
application-health confirmation changes.

Connect with existing host tools. In a configured Mosaico workspace, run:

```sh
python mosaico.py iris logs
```

Alternatively, use [Iris Gateway/Workbench](../ESP-Iris/components/esp_iris/tools/README.md)
to view logs. Verify application-task logs are visible and application behavior remains normal after disconnecting.

## Add other capabilities when needed

| Needed capability | Additional integration |
| --- | --- |
| Enter Vibe Mode from an ordinary application through host commands and perform Mosaico automated update/acceptance | [Application Vibe Mode adapter and product configuration](../mosaico-tools/docs/application-integration.md) |
| Crash diagnostics and repeated-crash recovery | [Crash diagnostics example](../ESP-Iris/components/esp_iris/examples/crash_recovery/README.md) |
| RPC, screen mirroring/input and file services | [Iris example index](../ESP-Iris/components/esp_iris/examples/README.md) |

Add these as needed. Installing Vibe Mode alone or viewing logs does not require a complete toolchain migration first.
