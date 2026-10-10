# ESP-Iris examples

These projects are packaged with the ESP-Iris component and can be built
without a product BSP or GSP. Each example declares `lisir233/esp_iris` as a
managed dependency and uses `override_path` to select the containing component
during source development.

## Choose an example

| Example | Transport | What it validates | Extra setup |
| --- | --- | --- | --- |
| [`minimal`](minimal/README.md) | TCP, USB CDC0 + CDC1, USB Serial/JTAG, or all three | Identity, lifecycle, status, logs, and independent control/data session binding | TCP needs an application network interface to become reachable |
| [`tcp_wifi`](tcp_wifi/README.md) | TCP | Application-owned Wi-Fi STA, DHCP, and reconnect | Private Wi-Fi credentials |
| [`tcp_pairing`](tcp_pairing/README.md) | TCP | Challenge-HMAC authentication and persistent token provisioning | Private Wi-Fi credentials and pairing token |
| [`rpc_jobs`](rpc_jobs/README.md) | USB CDC0 + CDC1 | Echo/info RPCs and a cancellable long-running job | Separate programming interface |
| [`display_input`](display_input/README.md) | USB CDC0 + CDC1 | Pull screenshot backend, screen mirror, and pointer RPC | Separate programming interface |
| [`media_streams`](media_streams/README.md) | USB CDC0 + CDC1 | RGB565/RGB888/JPEG/PNG image profiles and PCM S16LE audio | Separate programming interface |
| [`file_transfer`](file_transfer/README.md) | USB CDC0 + CDC1 | Streamed files, directories, rename, and safe deletion on FATFS | Separate programming interface and 2 MB partition layout |
| [`ota`](ota/README.md) | USB CDC0 + CDC1 | Recovery-first/direct OTA, A/B slots, acceptance, and rollback | 16 MB flash layout and separate programming interface |
| [`file_service`](file_service/README.md) | USB CDC0 + CDC1 | Bounded FATFS file browsing, streaming transfer, and mutations | 2 MB flash layout and separate programming interface |
| [`crash_recovery`](crash_recovery/README.md) | USB CDC0 + CDC1 | Retained Core Dump and crash-threshold factory recovery | 16 MB flash layout and separate programming interface |
| [`lifecycle`](lifecycle/README.md) | USB CDC0 + CDC1 | Stop, unregister, re-register, restart, and reconnect | Separate programming interface |

Start with `minimal`, then choose a focused example for the service you are
integrating.

## Common build workflow

From the repository root:

```bash
idf.py -C components/esp_iris/examples/minimal -B build-minimal build
```

From a downloaded example directory:

```bash
idf.py build
```

The ESP32-S31 example defaults select QIO. When reusing an existing `sdkconfig`,
select QIO in `idf.py menuconfig` as well; defaults do not overwrite saved choices.
The SDK still generates `--flash-mode dio` for the bootloader image and enables
QIO during bootloader initialization.

Use a stable serial path when flashing and verify the intended board first:

```bash
idf.py -p /dev/serial/by-id/<programming-port> flash
```

Application USB CDC0 is the text console for stock `idf.py monitor` and Iris
commands. CDC1 is the independent binary data link. Gateway and monitor take
turns owning the console; no device mode switch is needed. Flashing uses the
board's ROM download interface.

## Local secrets

The TCP Wi-Fi examples intentionally commit no credentials. Put local values
in `sdkconfig.local.defaults` beside the example README. The file is ignored by
Git and excluded from the Registry archive. Generated `sdkconfig` files may
also contain credentials and must not be committed or published.

## Related documentation

- [Component quick start](../README.md#quick-start)
- [Chinese quick start](../README_zh.md#快速开始)
- [Developer Gateway and Workbench](../tools/README.md)
- [Wire protocol](../protocol/spec.md)
