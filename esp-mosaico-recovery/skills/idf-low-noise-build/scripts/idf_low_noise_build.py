#!/usr/bin/env python3
"""Compatibility entrypoint for the public build runner."""
from pathlib import Path
import runpy

_runner = Path(__file__).resolve().parents[4] / "mosaico-tools/skills/idf-low-noise-build/scripts/idf_low_noise_build.py"
globals().update(runpy.run_path(str(_runner), run_name=__name__))
