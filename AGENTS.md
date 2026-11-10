# ESP-Mosaico Utils

Vibe Mode is the user-facing maintenance firmware; ROM Download Mode is the
chip downloader without ESP-Iris. Keep Recovery commands, wire identifiers,
public APIs and ABI stable unless the task requires a migration.

## Start here

Read the owning source and relevant tests only. Use [WORKFLOW.md](WORKFLOW.md)
for commands when needed. Do not preload specifications, validation journals,
release history, generated UI/assets, build trees or dependencies. Search the
owning directory first; keep logs on disk and report short error excerpts.

- `ESP-Iris/`: reusable IDF component, protocol, Gateway and Web Workbench.
- `mosaico-tools/`: host CLI, templates, public Recovery ABI, app adapter and bootloader.
- `shared/`: consumer-independent GSP acquisition and Ideas display resources;
  never import consumer implementations or locate their private files.
- `firmware/recovery/`: pre-built Vibe Mode bundle for reviewed Recovery operations.
  Do not commit generated binaries to the source checkout.

No nested Iris submodule. Apps, BSP pins and `.mosaico.json` belong to consuming
workspaces.

## Documentation

Keep one public version of each document. Root documentation and `docs/` must
be suitable for direct publication, with links that resolve in the public tree.
Keep internal workflows and implementation references in excluded internal
documentation or the owning private directory, preserving necessary context
when moving it out of a public file. Read the owning directory's `AGENTS.md`
for additional development instructions.

## Editing and verification

- Preserve unrelated work. Use ESP-IDF C/C++ APIs, English comments and commit
  messages. After native changes review affected CMake, manifests and sdkconfig.
  Drivers cover init/errors/deinit/thread safety; make pin assignments explicit.
  Avoid large new dependencies without approval.
- Run the smallest existing check for the changed behavior. Documentation alone
  needs no build; a UI edit needs the relevant native scenario, not all services.
  Widen for shared contracts or failures outside the owner. See WORKFLOW.md.
- Reuse compatible build directories. Finish edits before one incremental native
  build; repeat only checks affected by later edits. Stop when relevant checks pass.
- Do not add tests that merely pin wording, source spelling or implementation
  shape. Keep tests for observable behavior, failures and data integrity.
- Local review does not require a version bump, release validation or hardware
  deployment. Report actual checks and any remaining hardware validation.

## Releases and devices (only when in scope)

Vibe Mode, Iris and Tools have independent versions and tags: `vX.Y.Z`,
`esp-iris-vX.Y.Z` and `esp-mosaico-tools-vX.Y.Z`, respectively. Current
Recovery ABI is 2, layout version 5. Do not add 0.1 protocol compatibility or
downgrade device versions to match Tools. Version sources are Iris
`components/esp_iris/idf_component.yml` and Tools `tools/mosaico_cli/__init__.py`
under their owning directories.

Perform product Recovery/device operations through the consuming workspace's
`mosaico.py`. Validate standalone ESP-Iris with its own Gateway/CLI and IDF
examples; it must not depend on Mosaico Tools or private product firmware.
Do not erase credentials, identity, user data or partitions without explicit
authorization. Vibe firmware requires ESP-IDF >=6.2 and ESP32-S31.
