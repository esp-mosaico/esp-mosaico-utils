# Local changes

Baseline: `espressif/spi_nand_flash` **1.4.4**, commit `cc69ba1ff55bafd9cc39d0694984e72e0517cb08`.
This is a modified local copy; the manifest version denotes the upstream baseline. Original licenses are retained.

- Prepare and verify QE before quad pin routing.
- Clear and sync the logical map only for confirmed formatting (BDL command `0x95`).
- Remove forced GC after logical erase; retain TRIM, erased reads as FF, and Dhara automatic GC.
- Omit upstream test apps/helpers; normalize whitespace. ECC, bad-block policy and geometry are unchanged.

Interfaces: [mosaico_nand_extension.h](include/mosaico_nand_extension.h).
Selected through `main/idf_component.yml` with `override_path`. Reapply patches and rerun storage tests/builds when upgrading;
80MHz requires validation for each chip and board.

Original SHA-256:

- `src/dhara_glue.c`: `d528d949eb76e22bb61cd2da5fbf9ac0709517bf40c84ccc876eda6f9bc324dc`
- `src/nand_wl_blockdev.c`: `02b9d043fcb7bfd6038dcc067e682acf939dbad1240026d4e48617482082053d`
- `src/nand_impl.c`: `a6f0c575c9a0f184fc24c66aaa604f3bb7b5cb88666aaf7636efec57e12cdb3e`
