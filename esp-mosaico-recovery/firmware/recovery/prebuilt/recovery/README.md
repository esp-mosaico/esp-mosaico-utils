# Recovery 0.1 prebuilt bundle

This complete ESP32-S31 bundle is built from Recovery source commit
`a102c653b160a3e74af599ec159d597040e34171`. It includes the **Download From
Spark** primary action, Spark website guidance, Wi-Fi setup continuation and
USB Gateway pointer input. The normal Wi-Fi, TCP pairing and NAND update
entries remain available. Recovery remains version `0.1`.

The bootloader retains the black-background, orange dotted `mosaico` Logo.
Logo rendering is bootloader-only; applications and Recovery reset and fully
initialize the panel using their original BSP paths.

`manifest.json` records the source commit, offsets, sizes and SHA-256 of all
four images. The source commit identifies the implementation used to build
the bundle; the publication commit adds these generated artifacts.

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 23,424 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,730,592 bytes |

The factory slot remains 1,835,008 bytes. Bootloader, base partition table and
initial OTA selection bytes match the preceding bundle. The Recovery image's
embedded ELF SHA-256 is
`5f275c9bd1af5bd95ad8ddeeb4b4fffaef5558c9fd3a02a6b81b09dcf47181cc`,
matching the image validated on ESP-Mosaico v1.2: device screenshots, offline
page interactions, Gateway input, and normal → Recovery → normal transitions
passed. Wi-Fi connected continuation and an actual Spark download remain
unverified because network credentials were unavailable during validation.

Use the consuming workspace's `mosaico.py recover` for complete base
provisioning and `mosaico.py install` for normal applications. Do not copy one
image independently or flash this Recovery image into an application OTA slot.
Maintainers regenerate all images and the manifest atomically with the
`update-recovery-prebuilt` target after candidate validation.
