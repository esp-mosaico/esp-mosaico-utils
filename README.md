# ESP-Mosaico Utils

ESP-Mosaico Utils is the shared source repository for the ESP-Mosaico device
link and retained recovery toolchain. It intentionally starts with a clean Git
history while recording the source revisions used for the migration.

## Repository layout

| Path | Product | Release line |
| --- | --- | --- |
| `ESP-Iris/` | ESP-Iris component, Developer Gateway, and Web Workbench | `0.1.x` |
| `esp-mosaico-recovery/` | ESP-Mosaico CLI and retained Recovery firmware | `0.1.x` |

The release version of `esp-mosaico-recovery` describes the host toolchain.
The embedded Recovery firmware keeps its independent version. New source
builds and the prebuilt bundle use `0.1`. The bundle
retains its reviewed bootloader, partition table, and initial OTA data; its
Recovery application is rebuilt from this repository and validated on device.
Changing the checkout does not update firmware already on devices.

The ESP-Iris checkout also includes the prebuilt Web Workbench. The Gateway
serves it directly without Node.js; frontend contributors regenerate and commit
`ESP-Iris/components/esp_iris/tools/frontend/dist` with their source changes.

## Use from a firmware workspace

A consuming repository pins this repository once and references both products
from that checkout. For ESP-Mosaico-Vibe the intended layout is:

```text
submodule/esp-mosaico-utils/
├── ESP-Iris/
└── esp-mosaico-recovery/
```

Run device commands through the consuming workspace's root `mosaico.py`. The
workspace owns `.mosaico.json`, application projects, the BSP pin, and device
operation evidence. This utilities repository is not itself an application
workspace.

## Development checks

Create a Python environment and install the ESP-Iris host test dependencies,
then run:

```sh
python -m pytest -q esp-mosaico-recovery/tests
cd ESP-Iris/components/esp_iris/tools
python -m pytest -q --ignore=tests/e2e
```

Frontend, ESP-IDF build-matrix, resource-budget, and release checks are owned
by the root CI workflow. Hardware operations remain explicit and must run
through a consuming workspace's `mosaico.py` command.

## Versions and releases

The initial monorepo release candidates are ESP-Iris `0.1.0` and ESP-Mosaico
Tools `0.1.0`. Product-specific tags avoid collisions:

- `esp-iris-v0.1.0`
- `esp-mosaico-tools-v0.1.0`

See [VERSIONING.md](VERSIONING.md) for authoritative version surfaces,
[MIGRATION.md](MIGRATION.md) for source provenance and path changes, and
[LICENSES.md](LICENSES.md) for the current licensing boundary.
