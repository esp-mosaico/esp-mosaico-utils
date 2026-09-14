# Changelog

## Unreleased

- Set newly built Recovery firmware to version `0.1` for ESP-30, independently
  of the `0.1.0` host CLI version. Keep the Recovery ABI and partition layout.
- Accept two-part Recovery versions in System Update checks. Recovery `0.1`
  retains compatibility with legacy 2.x minimum versions through `2.8.5`,
  while rejecting newer requirements. Keep existing update bundles usable.
- Update the prebuilt Recovery application and generated manifest to `0.1`
  after device validation; retain the reviewed bootloader, partition table,
  and initial OTA data unchanged.

## 0.1.0 - 2026-09-10

- Establish ESP-Mosaico Tools as a `0.1.x` product in the
  `esp-mosaico-utils` monorepo.
- Move the host CLI and retained Recovery firmware into
  `esp-mosaico-recovery` without importing the former repository history.
- Consume the sibling ESP-Iris checkout from the same monorepo revision.
- Retain the reviewed `2.8.5-recovery` device image until its monorepo-built
  replacement completes hardware acceptance.
