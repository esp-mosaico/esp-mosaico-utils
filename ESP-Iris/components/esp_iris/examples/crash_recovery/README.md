# Retained Core Dump and factory recovery

This destructive dual-CDC USB example demonstrates Iris' default crash-loop
recovery policy on a 16 MB layout. A normal OTA application deliberately
crashes after startup, but the injection path does not increment a counter or
select a partition. On the following boot, `esp_iris_boot_probe()` attributes
the panic reset to the previously started application. At the configured Iris
threshold (one for this example), Iris commits the failure record, selects the
factory image, and performs a planned software restart. The original Flash
Core Dump remains available in factory Recovery.

The bootloader rollback feature is intentionally not used: a threshold greater
than one must be allowed to restart the same application repeatedly.

## Standalone setup

Create this example from the Component Registry, then run the commands below
from its directory:

```bash
idf.py create-project-from-example "espressif/esp_iris=0.2.0:crash_recovery"
cd crash_recovery
```

With a source checkout, change to `ESP-Iris/components/esp_iris/examples/crash_recovery`
from the repository root instead. These application USB examples require an SDK
supporting ESP32-S31; the release matrix uses the pinned IDF 6.2 revision.
After the first build downloads the component, prepare its bundled Gateway:

```bash
python esp_iris.py setup
python esp_iris.py doctor
python esp_iris.py web
```

The launcher uses an isolated cached environment and does not change the IDF
Python environment. Close the Gateway before flashing or monitoring its ports.

## Build and install factory recovery

Verify the physical flash size and target before the first full flash:

```bash
idf.py \
  -B build-crash-recovery \
  -D SDKCONFIG="$PWD/build-crash-recovery/sdkconfig" \
  -D SDKCONFIG_DEFAULTS=sdkconfig.recovery.defaults build
idf.py \
  -B build-crash-recovery -p /dev/serial/by-id/<programming-port> flash
```

Build the crashing application:

```bash
idf.py \
  -B build-crash-application \
  -D SDKCONFIG="$PWD/build-crash-application/sdkconfig" \
  -D SDKCONFIG_DEFAULTS=sdkconfig.application.defaults build
```

With recovery connected, transfer `build-crash-application/esp_iris_crash_recovery.bin`
using application execution mode. After the application crashes, the same
device ID reconnects in factory recovery.

```bash
IRIS=esp_iris.py
python "$IRIS" ctl ota DEVICE_ID \
  build-crash-application/esp_iris_crash_recovery.bin \
  --elf build-crash-application/esp_iris_crash_recovery.elf \
  --execution-mode application --wait
python "$IRIS" ctl crash DEVICE_ID
python "$IRIS" ctl coredump DEVICE_ID retained-core-dump.bin
python "$IRIS" ctl rpc-raw DEVICE_ID 5120 1
```

RPC `0x1400/1` returns four little-endian words: Iris count, Iris limit, last
application address, and flags (`bit0=injection enabled`, `bit1=recovery
pending`). RPC `0x1400/2` calls `esp_iris_crash_loop_reset()`, disables
injection, and resumes the application. RPC `0x1400/3` clears the same Iris
record, re-arms injection, and retries it. Both restart RPCs delay reboot long
enough for their responses to drain.

To validate a threshold of three, set
`CONFIG_ESP_IRIS_CRASH_LOOP_LIMIT=3` in an ignored local defaults file
for both profiles. Recovery never exits automatically.

Return to the [example index](../README.md).
