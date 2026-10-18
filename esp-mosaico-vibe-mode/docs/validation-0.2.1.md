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

This release supports plaintext developer hardware with secure boot and Flash
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
Hardware qualification and replacement prebuilt hashes are recorded after the
consuming framework validates the frozen clean-source bundle. Existing reviewed
prebuilt bytes are retained until that qualification succeeds.
