# Recovery 0.2.1 single-slot handover

Recovery and normal applications use the reviewed ESP-IDF
`188e3e55bb20505b5fa9dc49ee390bf42c58b4ee` on ESP32-S31. The supply component
retains the startup DREG correction and the digital-system restart boundary
previously exercised by the IDF188 handover experiment. Boot clears inherited
USB DMA before loading application RAM. The firmware version is `0.2.1`;
ESP-Iris and tools keep their independent version numbers.

The immutable ABI 2 prefix is unchanged. There is exactly one normal app/ota_0
at `0x210000`, with a product-owned label and sector-aligned capacity within
16 MiB. The default official table remains `main_app` / `0xdf0000`; framework
products use `ota_0` / `0x700000`. Native CMake, System Update and Ideas tools
resolve the subtype, and reject factory or alternate OTA slots. Recovery bundle
metadata records the label and capacity from the actual checksum-verified table.

The guard never treats an old VALID metadata copy as a different physical
rollback image. It normalizes the obsolete metadata sector, verifies the entire
erased sector, grants one NEW trial, and verifies the SDK's NEW-to-PENDING write.
Unhealthy PENDING stays durable and boots Recovery on subsequent resets. Read,
erase, write, ambiguous-state and geometry failures never select the normal app.
The lower NEW exception beside a newer INVALID/ABORTED copy is restricted to the
reviewed bootstrap and pinned SDK update protocol; arbitrary imported otadata
is not a supported migration path. No forced health acceptance is used.

This revision supports plaintext developer hardware with secure boot and Flash
encryption disabled. CMake rejects secure boot, encryption and anti-rollback
configurations. The boot guard also checks the security eFuses before reading or
normalizing otadata. Provisioning must validate the same unfused configuration.
Encrypted metadata erasure and secure provisioning are not supported.

The custom selector intentionally removes generic IDF factory-reset and test-GPIO
selection branches: retained Recovery uses the explicit AI button, bootstrap
marker and NVS intent; generic options are disabled in the reviewed defaults.
Deep-sleep resume also passes through the guard. Actual IDF188 image-loading code
tries the only normal slot once, skips the absent factory/alternate slots, then
loads Recovery. A selected Recovery with an invalid image resets without trying
an application.

Run the compiled host fault model with:

```sh
python esp-mosaico-vibe-mode/firmware/vibe-mode/tools/check_boot_policy.py \
  --candidate-project esp-mosaico-vibe-mode/firmware/vibe-mode \
  --idf-path "$IDF_PATH"
```

The model compiles actual current selector functions plus pinned SDK CRC,
selection, image-loading, update and health functions. It exercises 25 scenarios
for both normal-slot capacities (50 cases), including interrupted writes,
post-write read failures, obsolete-copy aliasing and invalid image fallback.
The host regression suite covering application configuration, boot intent,
packaging, native layout, retained contracts and Ideas passes 98 tests plus
19 subtests. Five introduced component/discovery fixture expectations were
updated and 31 focused tests pass without skips. Six actual Linux CJSON worker,
backend and Recovery resilience tests pass without skips, including both OTA0
labels/capacities and rejection of shifted, flagged or alternate app slots.
A broader macOS run retained local OpenSSL/libraqm/ASAN limitations; it is not
reported as a full upstream-suite pass.

## Qualified frozen bundle (2026-10-18)

The checked-in prebuilt is copied byte-for-byte from a clean source build at
`0bbf1c8afa99919349acbc4efcb59e9cbff35597`, using the exact IDF revision above.
The build completed in one attempt, including the retained-slot and USB BSS
checks. No firmware rebuild occurred between freezing, hardware qualification
and prebuilt promotion. The source commit remains available in this branch;
later commits add host tests, documentation and these prebuilt bytes.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Recovery | 1,493,728 | `b56736f43cb6817c9350a855618ff5cd3037849c7d0f5b02222c92762d995f2a` |
| Bootloader | 22,784 | `ee533601822f1c697bfaedb8f6a01a6d008206574bf2e268cec690fe88807848` |
| Official partition table | 3,072 | `ff7ac35a4f2e51424150a6ba56172174299baa737230a09792dd46e8f5d0bb99` |
| Bootstrap otadata | 8,192 | `5a5d79a1c029da23a3b9cc03c111c5b72f9cbfa386877b0a5d20dc93ab42c7e1` |
| Bundle manifest | — | `a5906dd394f47133d63fd3c1f7bca0c40ee60ae625f5fdd124f93c41bfaa33ef` |

The bootloader leaves 1,792 bytes in its immutable 24 KiB window. Recovery ELF
SHA-256 is `3321548c1b61f95f133290f0a7284ebb00382912b9e6890ac2d47e502174a061`.
The official default partition table remains unchanged (`main_app/0xdf0000`).

One plaintext, unfused ESP32-S31 board was qualified through the consuming
framework's Gateway. Its existing framework `ota_0/0x700000` partition table and
application NVS were preserved byte-for-byte. A single identity-checked ROM
session installed only the bootloader, Recovery and bootstrap otadata, with all
three image MD5 checks passing. The official default table was not written over
the framework's product/resource layout.

- Empty application metadata boots Recovery and stays in Recovery after a
  software restart (reset reason 3, crash count 0).
- A deliberately unaccepted normal diagnostic was observed PENDING. The host
  correctly reported an unknown outcome when no healthy event arrived; at the
  application's 90-second deadline it returned to the exact Recovery ELF above.
  A further Recovery restart stayed in Recovery instead of retrying that app.
- A canonical framework-template System Update was validated and accepted as
  healthy with ELF `d31c6f7ab4759a01db02c247ed6c913e0a62a48a2d3d03a49fb8fa32870bc1a8`.
  Its metadata was VALID, target 0, planned 0. A normal restart retained that
  state, reset reason 3, crash count 0, and restored Home counter value 1.

No forced-healthy RPC, application NVS wipe or NAND format was used. Private
backups and device-operation evidence stay outside Git. This is one-board
qualification; the official 13.9375 MiB normal-slot geometry is covered by the
compiled host model, and no population reliability claim is made.
