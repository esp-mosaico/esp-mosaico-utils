#!/usr/bin/env python3
"""Validate the published firmware with the same checks used before provisioning."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mosaico-tools" / "tools"))

from mosaico_cli.errors import EnvironmentError
from mosaico_cli.recovery import load_bundle


def main() -> int:
    try:
        manifest = load_bundle(ROOT / "firmware" / "recovery", "esp32s31")
    except EnvironmentError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Vibe Mode {manifest['version']}: all Recovery images verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
