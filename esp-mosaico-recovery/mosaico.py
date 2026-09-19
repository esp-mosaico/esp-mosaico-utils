#!/usr/bin/env python3
"""Compatibility launcher; implementation is owned by mosaico-tools."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "mosaico-tools/mosaico.py"), run_name="__main__")
