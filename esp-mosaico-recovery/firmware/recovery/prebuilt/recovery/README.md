# Recovery 0.1 prebuilt bundle

This complete ESP32-S31 bundle uses **ESP-GSP 1.4.0** and GSPC **0.5.0**
for the Vibe Mode UI. Recovery remains version `0.1`, ABI 1. It was generated
from source commit `6391e92bf22025ad4e0a590bcaa86e25f6802d9f` with the
uncommitted Bridge prefetch and lossless compression changes; `manifest.json`
records `source.dirty: true`.

The reviewed bootloader, base partition table and initial OTA selection bytes
match the preceding reviewed bundle. They were preserved as inputs when
atomically regenerating the complete bundle with the device-tested Recovery.
The bootloader retains the black-background, orange dotted `mosaico` logo.

`manifest.json` records the source, offsets, sizes and SHA-256 of all images.

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 23,424 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,831,984 bytes |

The immutable factory slot remains 1,835,008 bytes, with **3,024 bytes free**.
Zopfli 0.4.3 reduces the unchanged GSPB from 45,428 to 42,548 compressed bytes;
including the prefetch lifecycle, firmware size decreases by 2,368 bytes.
GSP initialization still uses the previously validated 20,480-byte main stack.

Device validation on 2026-09-20 used MAC `30:ed:a0:f4:51:8e` and verified
the embedded ELF SHA-256
`52a8726145ead301ca811c4024242531c283b21bddcb0232b220f5f948cbcbff`.
Recovery self-update preserved the live application layout. Home-page background
registration, the same code across Download → Home → Download, explicit cancel
followed by a new code, screenshots, and normal → Recovery → normal transitions
passed on the same Device ID with new Boot IDs. CLI and Workbench API identity
and update records matched. The device was left in Recovery on its home page,
with a newly prefetched code. ROM provisioning was not repeated in this change.

Host validation: 45 tests and 15 subtests passed, including the actual Bridge
worker against HTTP/RTOS fakes, native GSP interaction flows, compression
round-trip, font/product contracts and reviewed-bundle checks.

An actual Spark application download was not exercised. NAND firmware installation
was not validated. Background registration caches a code; remote inventory and
download polling begin only after opening Download Ideas. Back retains the code;
Cancel ends the session. Idle prefetch expires instead of renewing indefinitely.

Use the consuming workspace's `mosaico.py recover` for complete base provisioning
and `mosaico.py iris app-update` for normal applications. Do not copy one image
independently or flash Recovery into an application OTA slot. Regenerate the
complete bundle and manifest atomically only after candidate validation.
