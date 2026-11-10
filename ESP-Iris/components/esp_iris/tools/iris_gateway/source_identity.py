"""Runtime source provenance, separate from API compatibility."""
from __future__ import annotations

import functools
import hashlib
import pathlib
import subprocess
from typing import Any


def source_identity(source: pathlib.Path) -> dict[str, Any]:
    source = source.resolve()
    # Accept the historical Iris checkout root and standalone component roots.
    component = source if (source / "tools/iris_gateway").is_dir() else source / "components/esp_iris"
    tools = component / "tools"
    files = [component / "idf_component.yml", tools / "esp_iris.py", tools / "requirements.lock",
             tools / "rpc_catalog.json"]
    files += list((tools / "iris_gateway").glob("*.py"))
    files += [path for path in (tools / "frontend/dist").rglob("*") if path.is_file()]
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_file():
            # Preserve sha256-runtime-v1 for existing source checkouts while
            # making the digest independent of the installation directory.
            name = pathlib.PurePosixPath("components/esp_iris") / path.relative_to(component).as_posix()
            digest.update(name.as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    if not (tools / "iris_gateway").is_dir():
        raise ValueError(f"ESP-Iris runtime not found under {source}")
    revision = None
    try:
        result = subprocess.run(["git", "-C", str(component), "log", "-1", "--format=%H", "--", "."],
                                capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0:
            revision = result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass  # Component Registry archives need not contain Git metadata.
    return {"algorithm": "sha256-runtime-v1", "fingerprint": digest.hexdigest(), "git_revision": revision}


@functools.lru_cache(maxsize=1)
def running_source() -> dict[str, Any]:
    # Snapshot once at process start; later edits must not rewrite provenance
    # of an already running Gateway.
    return source_identity(pathlib.Path(__file__).resolve().parents[2])
