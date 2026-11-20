# Pull screenshot, screen mirror, and pointer input

This dual-CDC USB example implements the screen and pointer contracts without a
display driver, BSP, GSP, or framebuffer allocation.

The screen backend generates a deterministic 480 × 480 RGB565 pattern on
demand. The same bounded reader supports:

- one-shot screenshot capture; and
- continuous screen mirror tiles.

Pointer input uses RPC service `0x1001`, method `1`. The fixed 12-byte
little-endian payload is `<BBhhHI>`: phase, reserved byte, x, y, reserved word,
and sequence. The example validates and echoes the message so delivery can be
tested without a touch controller.

## Standalone setup

Create this example from the Component Registry, then run the commands below
from its directory:

```bash
idf.py create-project-from-example "espressif/esp_iris=0.2.0:display_input"
cd display_input
```

With a source checkout, change to `ESP-Iris/components/esp_iris/examples/display_input`
from the repository root instead. These application USB examples require an SDK
supporting ESP32-S31; the release matrix uses the pinned IDF 6.2 revision.
After the first build downloads the component, prepare its bundled Gateway:

```bash
python esp_iris.py setup
python esp_iris.py doctor
python esp_iris.py web
```

The launcher uses an isolated cached environment and does not change the IDF
Python environment. Close the Gateway before flashing or monitoring its ports.

## Build and flash

```bash
idf.py \
  -B build-display-input build

idf.py \
  -B build-display-input \
  -p /dev/serial/by-id/<programming-port> flash
```

CDC0 carries text logs and Iris commands for stock `idf.py monitor`; CDC1
carries binary data. Close Gateway before monitoring the same console. Flash
through the board's ROM download interface.

## Expected result

In the Workbench:

1. Capture a screenshot and verify the red/green gradient with a blue XOR
   pattern.
2. Start screen mirror at 1–60 FPS and confirm incremental updates.
3. Use the pointer gesture control and confirm that the echoed sequence is
   accepted.

For a product, replace the synthetic reader with a bounded, correctly locked
read from the display stack while keeping the same backend contract.

Return to the [example index](../README.md).
