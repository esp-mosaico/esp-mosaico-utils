"""Recovery must select its cached standalone GSPC before IDF configures GSP."""
import os
from pathlib import Path
import shutil
import subprocess
import venv

import pytest

UTILS_ROOT = Path(__file__).resolve().parents[2]
RECOVERY = UTILS_ROOT / "esp-mosaico-recovery/firmware/recovery"


def test_recovery_bootstraps_without_python_gsp_package(tmp_path):
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("CMake is required for the Recovery configure regression")
    # A fresh interpreter has no gsp package even when CI's Python does.
    python_root = tmp_path / "clean python"
    venv.EnvBuilder(with_pip=False).create(python_root)
    python = python_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    cache = tmp_path / "compiler cache"
    cache.mkdir()
    binary = cache / ("gspc.exe" if os.name == "nt" else "gspc")
    binary.write_bytes(b"cached compiler: resolution only")
    fake_idf = tmp_path / "idf"
    entry = fake_idf / "tools/cmake/project.cmake"
    entry.parent.mkdir(parents=True)
    # Stop at the IDF boundary, before component downloads or firmware compilation.
    entry.write_text(
        'file(WRITE "${CMAKE_BINARY_DIR}/resolved-gspc.txt" "${GSPC_EXECUTABLE}")\n'
        'message(FATAL_ERROR "test reached IDF configuration boundary")\n',
        encoding="utf-8",
    )
    environment = dict(os.environ, IDF_PATH=str(fake_idf), GSPC_CACHE_DIR=str(cache))
    for name in ("GSPC_EXECUTABLE", "PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    build = tmp_path / "build"
    result = subprocess.run(
        [cmake, "-S", str(RECOVERY), "-B", str(build),
         "-DMOSAICO_GSPC_PYTHON=" + str(python)],
        env=environment, capture_output=True, text=True, timeout=60,
    )
    output = result.stdout + result.stderr
    assert "test reached IDF configuration boundary" in output, output
    resolved = (build / "resolved-gspc.txt").read_text(encoding="utf-8")
    assert Path(resolved) == binary, output
    assert "ModuleNotFoundError" not in output
