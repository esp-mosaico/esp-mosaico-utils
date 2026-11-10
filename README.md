# ESP-Mosaico Utils

ESP-Mosaico Utils contains the ESP-Iris device link, Web Workbench and
ESP-Mosaico application toolchain. Vibe Mode uses ESP-Iris for installation and
device maintenance; ROM Download Mode is the chip-level flashing program.
Recovery commands, protocol identifiers and ABI names remain stable.

## Repository layout

| Path | Contents |
| --- | --- |
| `ESP-Iris/` | ESP-Iris component, Developer Gateway and Web Workbench (0.2.x) |
| `mosaico-tools/` | Host CLI and build runner (0.2.x), templates, public Recovery ABI, application adapter and bootloader integration |
| `firmware/recovery/` | Pre-built Vibe Mode bundle for reviewed Recovery operations |
| [`shared/`](shared/README.md) | GSP tool acquisition and Ideas display-resource generation |

The Gateway serves the committed Web Workbench without Node.js. Frontend
contributors regenerate and commit
`ESP-Iris/components/esp_iris/tools/frontend/dist` with their source changes.

## Use from an application workspace

Pin this repository once and resolve Iris and Tools from the same revision.
Run device commands through the consuming workspace's root `mosaico.py`.
The workspace owns `.mosaico.json`, applications, BSP pins and device evidence.

```sh
# Uses firmware/recovery.
python mosaico.py recover --source reviewed

# Requires an explicitly supplied firmware project.
python mosaico.py recover --source current --source-path /path/to/firmware/vibe-mode

# Validate an app against that project's prepared candidate.
python mosaico.py iris app-update --recovery-source current --recovery-source-path /path/to/firmware/vibe-mode
```

Source paths are relative to the current working directory. `current` without a
path fails before building or accessing a device. See
[application integration](mosaico-tools/docs/application-integration.md) and
[0.2 migration](mosaico-tools/docs/migration-0.2.md).

## Development

Start with [AGENTS.md](AGENTS.md) and use [WORKFLOW.md](WORKFLOW.md) for the
check matching the changed owner. Ordinary edits use focused tests and cached
builds. Full host, frontend and firmware checks remain available in CI.

Vibe Mode, ESP-Iris and ESP-Mosaico Tools have independent versions and release
tags: `vX.Y.Z`, `esp-iris-vX.Y.Z` and `esp-mosaico-tools-vX.Y.Z`, respectively.
