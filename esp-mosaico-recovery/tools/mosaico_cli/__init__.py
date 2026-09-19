"""Compatibility import path for pre-split consumers."""
from pathlib import Path

_package = Path(__file__).resolve().parents[3] / "mosaico-tools/tools/mosaico_cli"
__path__ = [str(_package)]
exec(compile((_package / "__init__.py").read_bytes(), str(_package / "__init__.py"), "exec"))
