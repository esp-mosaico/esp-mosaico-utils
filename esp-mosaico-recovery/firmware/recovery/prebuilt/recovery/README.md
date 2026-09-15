# Recovery 0.1 prebuilt bundle

The Recovery application reports version `0.1`. `manifest.json` records its
source revision and the size, offset, and SHA-256 of every image. The bootloader,
partition table, and initial OTA data are retained byte-for-byte from the
previously reviewed base bundle. The manifest source revision describes the
Recovery application; it does not claim those retained images were rebuilt.

On 2026-09-14 the application passed Gateway-driven self-update on ESP32-S31.
The device reported healthy Recovery `0.1`, and its ELF identity matched the
build. An update bundle requiring the old 2.x release line was rejected with
`ESP_ERR_INVALID_VERSION` before writing. A bundle with the same verified
application and data bytes and a `0.1` minimum restored the original
`cyber_ride` ELF hash. The Device ID remained stable and Boot IDs changed.
No credentials or user NVS were erased. Fresh ROM provisioning of the complete
base bundle was not repeated.

All four bundle images passed manifest size/hash checks, the Recovery image
fits the unchanged factory slot, and its embedded version is `0.1`. The build
used IDF revision `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` with
pre-existing local modifications, as reflected in the manifest's IDF version.
This does not attest to a clean release build.

Structured device-operation records and raw logs are retained in the consuming
Vibe workspace under `.codex-runs/esp-30-prebuilt/` and `.codex-runs/mosaico/`.
Archive them with release evidence before publishing a formal release.
