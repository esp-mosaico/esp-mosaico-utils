"""Download published Engine examples with IDF's Component Registry workflow."""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path
import tempfile

from .errors import EnvironmentError, SelectionError
from .host import HostEnvironmentError, prepare_idf_environment
from .raylib_toolchain import descriptor, use_registry_engine

RELEASED_EXAMPLES = (
    "sky_hop",
    "raylib_shooter",
    "tower_defense",
    "last_zone_extraction",
    "living_worlds",
    "neon_rift_rally",
)
REQUIRED_FILES = (
    "CMakeLists.txt",
    "main/CMakeLists.txt",
    "main/idf_component.yml",
    "game.sim.json",
    "shared/common_components/examples_common/project.cmake",
)


def _ready(path, identity):
    try:
        return json.loads((path / ".mosaico-registry-example.json").read_text(encoding="utf-8")) == identity and all(
            (path / name).is_file() for name in REQUIRED_FILES
        )
    except (OSError, ValueError):
        return False


def ensure_example(workspace, name):
    """Return a published, versioned local example; never fall back to repo examples."""
    if name not in RELEASED_EXAMPLES:
        raise SelectionError(f"Not a released game example: {name}. Choose one of {', '.join(RELEASED_EXAMPLES)}.")
    pin = descriptor(workspace.tool_root)
    identity = {"component": pin["component"], "version": pin["version"], "example": name}
    cache = workspace.run_dir / "registry-examples" / pin["version"] / name
    if _ready(cache, identity):
        return cache
    if cache.exists():
        raise EnvironmentError(
            f"Incomplete Registry example cache: {cache}. Preserve local changes before removing this cache and retrying."
        )
    from .runtime import RunContext, resolve_idf_path

    context = RunContext(workspace, "registry-example", False, True)
    try:
        sdk = prepare_idf_environment(resolve_idf_path(workspace))
    except HostEnvironmentError as error:
        raise EnvironmentError(str(error)) from error
    cache.parent.mkdir(parents=True, exist_ok=True)
    specification = pin["component"] + "=" + pin["version"] + ":" + name
    context.status("example: downloading " + specification)
    print("Downloading Registry example " + specification, file=sys.stderr)
    try:
        with tempfile.TemporaryDirectory(prefix=".example-fetch-", dir=cache.parent) as temporary:
            # idf.py creates the example-named child in cwd. Avoid --path: some
            # IDF frontends interpret it as a second action after the download.
            result = context.run(
                [sdk.python, sdk.idf_py, "create-project-from-example", specification],
                cwd=Path(temporary),
                env=sdk.values,
                timeout=300,
            )
            if result.returncode:
                raise EnvironmentError(f"Registry example download failed. Log: {context.log_path}")
            prepared = Path(temporary) / name
            if not all((prepared / filename).is_file() for filename in REQUIRED_FILES):
                raise EnvironmentError(f"Registry example is missing its shared launcher or sources: {specification}")
            use_registry_engine(prepared / "main/idf_component.yml", workspace.tool_root)
            (prepared / ".mosaico-registry-example.json").write_text(
                json.dumps(identity, indent=2) + "\n", encoding="utf-8"
            )
            try:
                prepared.rename(cache)
            except OSError:
                if not _ready(cache, identity):
                    raise
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EnvironmentError(f"Cannot prepare Registry example: {error}. Log: {context.log_path}") from error
    return cache
