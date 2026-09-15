# Recovery 0.1 prebuilt bundle

The Recovery application reports version `0.1` and embeds the production
`https://iris-bridge.esp-claw.com` Bridge Origin. `manifest.json` records the
clean utility source revision and the size, offset, and SHA-256 of every image.
The bootloader and Recovery application were rebuilt together; the partition
table and initial OTA data remain byte-for-byte identical to the previous
reviewed bundle.

On 2026-09-15 the complete candidate bundle passed ROM provisioning on an
ESP-Mosaico v1.2 ESP32-S31 board with hardware MAC `30:ed:a0:f4:51:56`, using
the consuming workspace's `mosaico.py recover --source current` launcher.
The launcher verified image hashes after write and observed healthy Recovery
`0.1` on Device ID `4553502d49524953010030eda0f45156`. The live firmware
ELF SHA-256 was `10ae5e16139fd6486255a9fc582da5776c1987e2e6cdfa031f046652bd286a55`,
matching the built image descriptor. The v1.2 display showed the Recovery UI.
No credentials, Device ID, or user NVS were erased. This exact candidate was
then promoted to the checked-in prebuilt bundle.

On 2026-09-14 the application passed Gateway-driven self-update on ESP32-S31.
The device reported healthy Recovery `0.1`, and its ELF identity matched the
build. An update bundle requiring the old 2.x release line was rejected with
`ESP_ERR_INVALID_VERSION` before writing. A bundle with the same verified
application and data bytes and a `0.1` minimum restored the original
`cyber_ride` ELF hash. The Device ID remained stable and Boot IDs changed.
No credentials or user NVS were erased. Fresh ROM provisioning of that earlier
base bundle was not repeated during the ESP-30 self-update test; the new
Bridge-enabled bundle above did receive complete ROM provisioning.

All four new bundle images passed manifest size/hash checks, the Recovery image
fits the unchanged factory slot, and its embedded version is `0.1`. The new
build used IDF revision `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` with
pre-existing local modifications, as reflected in the manifest's IDF version.
The utility source revision is clean, but the IDF checkout is not; this does
not attest to a fully clean release build.

Structured device-operation records and raw logs are retained in the consuming
Vibe workspace under `.codex-runs/esp-30-prebuilt/` and `.codex-runs/mosaico/`.
Archive them with release evidence before publishing a formal release.
