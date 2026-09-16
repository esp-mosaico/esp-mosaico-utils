# Recovery 0.1 prebuilt bundle

This complete ESP32-S31 bundle is built from the utilities-owned Recovery
project and includes the current ESP-Iris request/result and service-lifetime
implementation. Recovery remains version `0.1`; its retained partition
contract, OTA writer, internal logs and production HTTPS Bridge Origin are
unchanged.

The bootloader retains the black-background, orange dotted `mosaico` Logo.
Logo rendering is bootloader-only; applications and Recovery reset and fully
initialize the panel using their original BSP paths.

`manifest.json` contains the build-time source snapshot, offsets, sizes and
SHA-256 of all four images. Its source commit identifies the snapshot before
the publication changes were amended into that commit, not the final amended
publication commit ID.

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 23,424 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,729,760 bytes |

The factory slot remains 1,835,008 bytes. Bootloader, base partition table and
initial OTA selection bytes are unchanged from the preceding bundle.

Use the consuming workspace's `mosaico.py recover` for complete base
provisioning and `mosaico.py install` for normal applications. Do not copy one
image independently or flash this Recovery image into an application OTA slot.
Maintainers regenerate all images and the manifest atomically with the
`update-recovery-prebuilt` target after candidate validation.
