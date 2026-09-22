# Recovery 0.1 prebuilt bundle

Refreshed on **2026-09-22** from source commit
`151a631cfe176816570c9f9a8efd9cf7ea394d89`. The Recovery source was clean when
the manifest was generated (`source.dirty: false`). The build uses ESP-IDF
`v6.2-dev-2221-g7b9cc1ac79f-dirt`, ESP32-S31, ESP-GSP 1.4.0 and GSPC 0.5.0;
the IDF checkout's existing local modifications remain reflected in its version.
Recovery stays at version `0.1`, ABI 1, with the same retained partition contract.

This bundle includes the Download Ideas QR code and updated URL, OTA phase/rate/
progress display, PSRAM allocation and HTTPS throughput improvements, and the
compact splash bootloader with INFO logs on UART0 at 115200 baud.

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 24,432 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,812,880 bytes |

The 1,835,008-byte Recovery slot has **22,128 bytes free**. Recovery is 19,104
bytes smaller than the preceding prebuilt image. The bootloader has 144 bytes
free in its 24 KiB slot. The base partition table and initial OTA bytes are
identical to the preceding bundle; initial OTA data is erased (`0xff`) so the
base bundle starts in Recovery. `manifest.json` records every image's SHA-256.

## Artifact provenance

The Recovery image is the exact final, device-tested 20 KiB Bridge writer-stack
build. Its embedded ELF SHA-256 is:

`78e84733e66c5161efd53a6377939746ba35dee31372189aed4d7b36bc378103`

The bootloader is the exact artifact installed and accepted on the device during
the Logo/INFO-log validation. Its executable content matches the current build;
the rebuilt file differs only in descriptor compilation time, image checksum and
appended digest. The accepted binary is retained to preserve its hardware-tested
identity. Its SHA-256 after padding the entire 24 KiB slot with `0xff` is:

`d46d0987d7c39faa035ac78537e93d8b0d37ad3f3455cc428fe70d97a217a054`

All four images and the manifest were staged atomically by
`tools/prepare_recovery.py`, the packer used by `update-recovery-prebuilt`, with
the accepted bootloader supplied as an explicit input. No individual image was
replaced inside a previously generated manifest. The standard reviewed-source
`mosaico-recover-prepare` target then validated and staged this complete bundle;
the product CLI's `load_bundle` accepted it and the staged bytes matched.

## Validation and limits

Device validation used Device ID `4553502d49524953010030eda0f4518e`, MAC
`30:ed:a0:f4:51:8e`, board v1.2. The operator confirmed the black/orange `mosaico`
Logo and transition into Recovery. Recovery self-update verified the final ELF
and healthy state (operation `4982ef7f-dc2b-423b-a347-310a41e441dd`). Subsequent
USB system update verified the target Hello World ELF and healthy state
(operation `8fdad35d-12ca-4b29-bf17-a2ddea1c11e1`). Both preserved the live
application partition table and bootloader.

The final Recovery also completed a cloud update on 2026-09-22 at 15:21:52 +08,
then booted the expected healthy application with Boot ID
`7515106970987350574`. Recovery Boot ID was `1338705541141102194`; application
download/write took 8.964 seconds for 1,259,472 bytes (about 137.2 KiB/s).

A preceding attempt at 15:19:23 +08 aborted with `ESP_ERR_INVALID_STATE` after
the application component passed readback verification, at the subsequent
progress/cancellation gate. The captured logs do not identify the HTTP response
or cancellation source. This intermittent cloud-control failure remains under
investigation; refreshing the prebuilt bundle does not resolve it.

The firmware checks passed 306 host tests and 60 subtests, plus 12 native UI
tests; the final stack adjustment passed the three Bridge checks again with
ASan/UBSan. This package refresh passed 17 bundle/workspace/version/contract
tests and three subtests, manifest/hash/slot checks, and the default reviewed
preparation path. ROM provisioning was not repeated for this package refresh.
TCP/NAND transfers, controlled network-interruption retries and power-loss
testing remain outside the completed hardware validation.

Use the consuming workspace's `mosaico.py recover` for complete base provisioning
and its ESP-Iris application update commands for normal applications. The base
table is distinct from an installed application's layout; preserve the live table
when creating a Recovery-only self-update package. Maintain the complete bundle
and manifest together when regenerating these artifacts.
