# Recovery 0.1 prebuilt bundle

This complete ESP32-S31 bundle uses **ESP-GSP 1.4.0** and GSPC **0.5.0**
for the Vibe Mode UI. Recovery remains version `0.1`, ABI 1. It was generated
from source commit `2f8b983ceb92e3c7167735814a0ecb2c434dbd7f` with the
uncommitted GSP upgrade and startup-stack fix; `manifest.json` accurately
records `source.dirty: true`.

The bootloader retains the black-background, orange dotted `mosaico` logo.
Logo rendering is bootloader-only; applications and Recovery initialize the
panel through the BSP. The base partition table and initial OTA selection
bytes match the preceding reviewed bundle.

`manifest.json` records the source, offsets, sizes and SHA-256 of all four images.

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 23,424 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,834,352 bytes |

The immutable factory slot remains 1,835,008 bytes, with **656 bytes free**.
GSP 1.4 synchronously initializes the UI on the caller's stack. The main task
now uses 20,480 bytes; device logs measured 16,824 bytes remaining after UI
initialization. The previous 3,584-byte configuration rebooted during startup.

Device validation on 2026-09-20 used MAC `30:ed:a0:f4:51:8e` and verified the
embedded ELF SHA-256
`115c82f0169080e003963b91da961e69d142eacf1980b1e7d89efb0c8c3da083`.
Complete ROM recovery, Vibe Mode screenshots, Wi-Fi scanning, keyboard input
and cancellation, system update, and normal → Recovery → normal transitions
passed on the same Device ID with new Boot IDs. The device was left running
the GSP 1.4 Hello World application.

An actual Spark download was not exercised. The NAND page reported
`NAND unavailable: 0xffffffff`; NAND firmware installation was not validated.

Use the consuming workspace's `mosaico.py recover` for complete base
provisioning and `mosaico.py iris app-update` for normal applications. Do not
copy one image independently or flash Recovery into an application OTA slot.
Maintainers regenerate all images and the manifest atomically with
`update-recovery-prebuilt` after candidate validation, then update this note.
