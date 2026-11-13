"""Pinned Host/example tools; firmware resolves the Engine from the Registry."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request

from .errors import EnvironmentError

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
REQUIRED_FILES = (
    "host/run_game.py",
    "tools/game_cli.py",
    "idf_component.yml",
    "CMakeLists.txt",
    "examples/common_components/examples_common/project.cmake",
    "examples/boards/esp-mosaico/idf_component.yml",
)


def descriptor(tool_root):
    try:
        value = json.loads((tool_root / "raylib-toolchain.json").read_text(encoding="utf-8"))
        if value["schema_version"] != 1 or not all(
            isinstance(value[key], str) and value[key]
            for key in ("revision", "archive_url", "archive_sha256", "version", "component")
        ):
            raise ValueError("invalid Raylib toolchain descriptor")
        return value
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EnvironmentError(f"Cannot read pinned Raylib toolchain: {error}") from error


def cache_path(tool_root, run_dir):
    pin = descriptor(tool_root)
    return run_dir / "toolchains" / "raylib-lite-engine" / pin["revision"]


def _ready(path, pin):
    try:
        return json.loads((path / ".mosaico-toolchain.json").read_text(encoding="utf-8")) == pin and all(
            (path / name).is_file() for name in REQUIRED_FILES
        )
    except (OSError, ValueError):
        return False


def _download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "ESP-Mosaico-Tools"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        size = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError("Raylib toolchain archive exceeds size limit")
            output.write(chunk)


def _unpack(archive, destination, revision):
    """Copy only regular files/directories, never archive links or special files."""
    prefix = "raylib-lite-engine-" + revision
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if sum(member.size for member in members) > MAX_EXTRACTED_BYTES:
            raise ValueError("Raylib toolchain extraction exceeds size limit")
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] != prefix
                or "\\" in member.name
                or ":" in member.name
            ):
                raise ValueError(f"Unsafe Raylib archive path: {member.name}")
            if len(relative.parts) == 1:
                continue
            target = destination.joinpath(*relative.parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError(f"Missing Raylib archive content: {member.name}")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                if os.name != "nt":
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)


def ensure_toolchain(workspace):
    """Return an explicit developer checkout or publish a verified cache atomically."""
    selected = workspace.raylib_path
    if selected is not None:
        return selected  # Explicit dependencies.raylib; caller validates required entry points.
    pin = descriptor(workspace.tool_root)
    cache = cache_path(workspace.tool_root, workspace.run_dir)
    if _ready(cache, pin):
        return cache
    if cache.exists():
        raise EnvironmentError(
            f"Incomplete Raylib toolchain cache: {cache}. Preserve local changes and remove "
            "this cache before retrying, or configure dependencies.raylib explicitly."
        )
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".raylib-fetch-", dir=cache.parent) as temporary:
            temporary = Path(temporary)
            archive = temporary / "source.tar.gz"
            _download(pin["archive_url"], archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != pin["archive_sha256"]:
                raise ValueError("Raylib toolchain archive SHA-256 mismatch")
            prepared = temporary / "source"
            prepared.mkdir()
            _unpack(archive, prepared, pin["revision"])
            (prepared / ".mosaico-toolchain.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
            if not _ready(prepared, pin):
                raise ValueError("Raylib toolchain archive is missing required entry points")
            try:
                prepared.rename(cache)
            except OSError:
                if not _ready(cache, pin):  # Another creator may have published the same pin.
                    raise
    except (OSError, ValueError, tarfile.TarError) as error:
        raise EnvironmentError(f"Cannot prepare Raylib toolchain: {error}") from error
    return cache


def use_registry_engine(manifest, tool_root):
    """Remove the upstream creator's Engine override only in a new app manifest."""
    if not manifest.is_file():
        return
    component = descriptor(tool_root)["component"]
    version = descriptor(tool_root)["version"]
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    key = re.escape(component)
    entry = re.compile(r"^( *)(?:" + key + r"|'" + key + r"'|\"" + key + r"\")\s*:\s*(.*)$")
    output = []
    inside = False
    indent = 0
    for line in lines:
        match = entry.match(line.rstrip("\r\n"))
        if match:
            if match.group(2).startswith(("{", "[", "|", ">", "&", "*", "!")):
                raise EnvironmentError(f"Unsupported Engine dependency format in {manifest}; manifest unchanged.")
            indent = len(match.group(1))
            output.append(" " * indent + component + ': "==' + version + '"\n')
            inside = True
            continue
        if inside and line.strip() and not line.lstrip().startswith("#"):
            level = len(line) - len(line.lstrip())
            if level <= indent:
                inside = False
            else:
                child = re.match(r"(?:version|override_path)\s*:\s*(.*)$", line.lstrip())
                if (level != indent + 2 or child is None or
                        child.group(1).startswith(("{", "[", "|", ">", "&", "*", "!"))):
                    raise EnvironmentError(
                        f"Unsupported nested Engine dependency in {manifest}. "
                        "Only version and override_path scalars can be pinned; manifest unchanged."
                    )
                continue
        output.append(line)
    manifest.write_text("".join(output), encoding="utf-8")
