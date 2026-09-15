# Changelog

## Unreleased

- Replace local HTTP triggers and URL downloads with the Recovery-owned HTTPS
  Bridge client, supporting partitions, layout and factory updates.
- Add USB `bridge-code` with bounded asynchronous pairing; remove
  `http-update-code` and `system-update --manifest-url` without aliases.
- Preserve complete RFC 3339 pairing expiry timestamps and report the overall
  pairing deadline when the final USB poll times out.
- Configure source-built ESP-Mosaico Recovery images to use the production
  `https://iris-bridge.esp-claw.com` Origin and `esp-mosaico` board ID.
- Refresh the reviewed `0.1` Recovery bootloader and application after complete
  ROM provisioning and v1.2 display acceptance; retain the byte-identical
  partition table and initial OTA data.

- Set newly built Recovery firmware to version `0.1` for ESP-30, independently
  of the `0.1.0` host CLI version. Keep the Recovery ABI and partition layout.
- Accept two-part Recovery versions in System Update checks, and reject old
  2.x update bundles and Recovery image rollback across release lines.
- Regenerate the prebuilt manifest from the validated Bridge-enabled build;
  keep the Recovery partition layout and ABI unchanged.

## 0.1.0 - 2026-09-10

- Establish ESP-Mosaico Tools as a `0.1.x` product in the
  `esp-mosaico-utils` monorepo.
- Move the host CLI and retained Recovery firmware into
  `esp-mosaico-recovery` without importing the former repository history.
- Consume the sibling ESP-Iris checkout from the same monorepo revision.
- Retain the reviewed device image until its replacement completes hardware
  acceptance.
