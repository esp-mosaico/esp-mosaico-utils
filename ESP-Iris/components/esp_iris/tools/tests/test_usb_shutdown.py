"""Stop S31 USB DMA before CPU reset without tearing down a running worker."""
import re
import subprocess
from pathlib import Path


def test_usb_shutdown_ownership_and_initialization_rollback(tmp_path):
    tests = Path(__file__).resolve().parent
    source = tests.parents[1] / "src/esp_iris_transport_usb.c"
    for name in re.findall(r'#include "([^"]+)"', source.read_text()):
        header = tmp_path / name
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text('#include "sdk.h"\n')
    copied = tmp_path / source.name
    copied.write_text(source.read_text())
    output = tmp_path / "usb-shutdown-test"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
        '-DUSB_SOURCE="' + str(copied) + '"',
        "-I" + str(tmp_path), "-I" + str(tests / "usb_host"),
        str(tests / "usb_host/main.c"), "-o", str(output),
    ], check=True, capture_output=True, timeout=30)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=10)
