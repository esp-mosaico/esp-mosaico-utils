# S31 supply and restart boundary

This private retained-Recovery component owns the reviewed IDF188 startup DREG
correction and the cache-safe PVT/digital-system restart path. Its startup hook
is retained by `mosaico_supply_include`, and the link wrapper intercepts
`esp_restart_noos`. It exposes no application-state interface. `_bss_end` is an
SDK linker boundary used by startup memory handling, not mutable shared state.

The counterpart used for hardware qualification is the consuming framework's
existing board supply implementation. See `docs/validation-0.2.1.md` for exact
source/binary provenance, one-board scope and the plaintext security contract.
