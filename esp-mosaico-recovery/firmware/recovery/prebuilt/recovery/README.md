# Recovery 0.1 prebuilt bundle

This bundle includes the retained bootloader's black-background, orange dotted
`mosaico` Logo and the matching BSP LCD handoff implementation. Recovery reports
version `0.1`, embeds the production `https://iris-bridge.esp-claw.com` Bridge
Origin, and retains the software SHA1 configuration introduced for Wi-Fi in
ESP-34. The partition table and initial OTA selection data remain byte-for-byte
identical to the previous reviewed bundle.

`manifest.json` records the clean utility source revision
`b3a67ce1bda1284e710f677c7260bfe99e208358`, offsets, sizes and SHA-256 of all four
images. Recovery's BSP dependency is pinned to
`aba1269ecafc34d2c690370bfcd6e51f3e7df8f1` so independent source builds also
include the handoff implementation.

## Build and package validation

On 2026-09-16 the pinned Recovery source was rebuilt for ESP32-S31 with zero
compiler warnings. `update-recovery-prebuilt` atomically published the complete
bundle after candidate validation and device acceptance; the checked-in
bootloader and application match the tested candidate bytes exactly.

- Bootloader: 23,456 bytes (`0x5ba0`); 1,120 bytes (`0x460`) remain in its fixed
  24 KiB range, using ERROR-only bootloader logging.
- Recovery application: 1,728,480 bytes, within the unchanged 1,835,008-byte
  factory slot.
- Partition table: 3,072 bytes at `0x8000`; initial OTA data: 8,192 bytes at
  `0x9000`. Both hashes are unchanged from the previous reviewed bundle.
- Manifest schema, image magic, layout, security settings, sizes and hashes
  passed the product bundle validator.
- Recovery host tests: 170 passed plus 45 subtests. Workspace boot Logo,
  retained Recovery and System Update contract tests: 15 passed.

The build used ESP-IDF revision
`7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` with pre-existing local modifications,
Python 3.12.3, and verified ESP32-S31 support. The Recovery utility source was
clean, but the IDF checkout was not; this is not a fully clean release-build
attestation.

## Device acceptance

An ESP-Mosaico v1.2 board with hardware MAC `30:ed:a0:f4:60:56` and Device ID
`4553502d49524953010030eda0f46056` accepted the recompiled candidate through the
consuming workspace's `mosaico.py system-update` launcher:

1. Recovery-only self-update, operation
   `62a2af9a-6a69-4335-9ef0-406dcfddf107`: new Boot ID
   `10763401593792953525`; healthy Recovery `0.1`; ELF SHA-256
   `2769b0ace6d0aa6a8b42e98e3f295024636123b8d233ca6cdbe63b3cd167811d`
   matched the candidate image descriptor.
2. Bootloader plus the device's unchanged GSP partition table, operation
   `e9b360da-bcf6-4ce2-adc3-5ad44e5f059e`: new Boot ID
   `14981715707388590585`; full 24 KiB bootloader readback SHA-256
   `d2bf457cf5c764cdddc84ee79b1e9091e432fd813c9ccd4a88a653cf1071949e`
   matched the padded candidate.
3. `mosaico.py install` returned the same device to healthy `gsp_hello` with
   Boot ID `16131398577361773906` and verified application ELF identity.

The developer physically observed the same Logo implementation during this
2026-09-16 session and confirmed that the dotted Logo and display were normal.
Retained application logs confirm LCD handoff, and the recompiled Recovery's
native screenshot shows its firmware update service ready. v1.0/v1.1 GPIO
branches are compiled but have not received physical device acceptance.

No whole-Flash erase, credential/identity overwrite, UI-resource overwrite or
layout migration was performed. The device kept its existing GSP table; its
recovery-critical prefix matches this base bundle. Fresh ROM provisioning of
the complete recompiled base bundle was not repeated: the first automatic ROM
connection attempt failed before any write, and the live Recovery-supported
System Update path was used instead. The unchanged base table and initial OTA
data retain their earlier reviewed provisioning evidence in Git history.

Raw logs and device screenshots are retained in the consuming Vibe workspace
under `.codex-runs/pr-boot-splash-20260916/` and `.codex-runs/mosaico/`.
Archive that evidence before publishing a formal release.
