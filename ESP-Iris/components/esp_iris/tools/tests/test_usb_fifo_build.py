"""An unsupported TinyUSB revision must never silently change memory placement."""
import subprocess
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[2]


def test_fifo_adapter_rejects_unknown_source_without_touching_output(tmp_path):
    source = tmp_path / "upstream.c"
    output = tmp_path / "generated.c"
    source.write_bytes(b"/* unreviewed upstream revision */\n")
    output.write_bytes(b"previous build artifact\n")
    result = subprocess.run([sys.executable, str(COMPONENT / "cmake/usb_fifo_psram.py"),
                             str(source), str(output)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Unsupported TinyUSB CDC source" in result.stderr
    assert source.read_bytes() == b"/* unreviewed upstream revision */\n"
    assert output.read_bytes() == b"previous build artifact\n"
