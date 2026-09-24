#!/usr/bin/env python3
"""Prepare pinned Recovery GSP dependencies without an ESP-IDF build.

Run with Python 3.10+ and esp-gsp-tools==0.1.1 installed. The host test
interpreter can subsequently switch to Python 3.8; the native build keeps
using this bootstrap interpreter. Both utilities and workspace CI use this.
"""
import argparse
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import urllib.request
from unittest.mock import patch
import zipfile

GSP_VERSION = "1.5.1"
GSPC_VERSION = "0.6.1"
COMPONENT_URL = (
    "https://components.espressif.com/api/downloads/"
    "?object_type=component&object_id=dcad3123-0dbb-4c0d-bca1-a0faa4fd2de2"
)
# The registry rebuilds ZIP timestamps on download. Pin names and file contents
# instead of container bytes; this matches the official Registry 1.5.1 package.
COMPONENT_CONTENT_SHA256 = "87d1a3842e3b1a3d12646f8c322e77bd234caa01f910e06518f4c8324be408b7"


def extract_verified_zip(data, archive_format, destination):
    """Work around 0.1.1 copying a ZipInfo instead of its opened byte stream.

    GspManager verifies the archive signature before invoking this hook.
    Keep the manager's path containment check and use no global site edits.
    """
    if archive_format != "zip":
        raise ValueError("Expected a Windows ZIP release")
    root = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError("Unsafe GSP archive path: " + member.filename)
            if member.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def install_tool(product, version):
    from gsp import manager

    if os.name == "nt":
        with patch.object(manager, "_safe_extract", extract_verified_zip):
            executable = manager.GspManager(product).resolve(version)
    else:
        executable = manager.GspManager(product).resolve(version)
    return str(executable.resolve())


def prepare(directory, compiler_only=False):
    environment = {"GSPC_EXECUTABLE": install_tool("gspc", GSPC_VERSION)}
    if not compiler_only:
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / f"esp-gsp-{GSP_VERSION}.zip"
        if not archive.is_file():
            with urllib.request.urlopen(COMPONENT_URL, timeout=120) as response:
                data = response.read()
            archive.write_bytes(data)
        with zipfile.ZipFile(archive) as bundle:
            digest = hashlib.sha256()
            for name in sorted(bundle.namelist()):
                if not name.endswith("/"):
                    digest.update(name.encode() + b"\0" + hashlib.sha256(bundle.read(name)).digest())
            if digest.hexdigest() != COMPONENT_CONTENT_SHA256:
                raise RuntimeError("ESP-GSP component contents checksum mismatch")
            bundle.extractall(directory)
        component = directory / "esp-gsp"
        if (component / ".gspc_version").read_text().strip() != GSPC_VERSION:
            raise RuntimeError("Component and GSPC pins disagree")
        environment.update(
            ESP_GSP_COMPONENT_DIR=str(component.resolve()),
            GSP_SIM_EXECUTABLE=install_tool("sim", GSP_VERSION),
            GSP_BUILD_PYTHON=sys.executable,
        )
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
            for key, value in environment.items():
                stream.write("{}={}\n".format(key, value))
    for key, value in environment.items():
        print("{}={}".format(key, value))
    return environment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".host-deps/gsp"))
    parser.add_argument("--compiler-only", action="store_true")
    args = parser.parse_args()
    prepare(args.directory.resolve(), args.compiler_only)
