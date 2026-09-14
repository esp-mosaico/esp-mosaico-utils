# Recovery 0.1 prebuilt bundle

The Recovery application reports version `0.1`. `manifest.json` records its
source revision and the size, offset, and SHA-256 of every image.

The application is built from source revision
`c4316c6608402b1db375ddccd8d5b821b21b6c8b`. The bootloader, partition table,
and initial OTA data are retained byte-for-byte from the previously reviewed
`2.8.5-recovery` bundle (source recorded there as
`b009032e10bdfb492fceddc9f6828f63a841c6cb`). The manifest source revision
describes the new Recovery application; it does not claim those retained
base images were rebuilt from that revision.

On 2026-09-14 the application passed Gateway-driven Recovery self-update on
ESP32-S31: image identity matched, the device reported `0.1` and healthy
Recovery, and the original `cyber_ride` System Update bundle restored the same
application ELF hash. Device ID remained stable and Boot IDs changed.
This also exercised compatibility with the old bundle's
`minimum_recovery_version: 2.5.0-recovery`. No credentials or user NVS were
erased. The new image was tested with the device's existing application layout;
fresh ROM provisioning of the complete base bundle was not repeated.

All four bundle images passed manifest size/hash checks, the Recovery image
fits the unchanged factory slot, and its embedded version is `0.1`.
The build used IDF revision `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` with
existing local modifications, as reflected by the manifest's IDF version.
This is not a claim of a clean, reproducible release build.

Structured device-operation records and raw logs are retained in the
consuming Vibe workspace under `.codex-runs/esp-30-prebuilt/` and
`.codex-runs/mosaico/`. Archive them with release evidence before publishing
a formal release. The previous bundle remains available in Git history.
