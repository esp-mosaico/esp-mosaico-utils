#!/usr/bin/env python3
"""Validate the release archive and exercise an isolated component installation."""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from ruamel.yaml import YAML


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and ((tag == "script" and key == "src") or (tag == "link" and key == "href")):
                parsed = urlsplit(value)
                if not parsed.scheme and not parsed.netloc:
                    self.paths.add(parsed.path.lstrip("/"))


def validate_archive(archive: Path, tag: str = "") -> tuple[dict[str, bytes], str]:
    files = {}
    forbidden = {".codex-runs", "node_modules", "__pycache__", "managed_components",
                 ".pytest_cache", ".mypy_cache", ".ruff_cache", "test-results", "playwright-report"}
    with tarfile.open(archive) as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError(f"Unsafe archive entry: {member.name}")
            if member.isdir():
                continue
            if (any(part in forbidden or part.startswith((".venv", "build-", "build_")) or part == "build"
                    for part in path.parts)
                    or path.suffix == ".tsbuildinfo" or path.name in {"sdkconfig", "sdkconfig.old", "dependencies.lock"}):
                raise ValueError(f"Development artifact in package: {path}")
            name = path.as_posix()
            if name in files:
                raise ValueError(f"Duplicate archive entry: {name}")
            files[name] = stream.extractfile(member).read()
    required = {"idf_component.yml", "CMakeLists.txt", "Kconfig", "LICENSE", "include/esp_iris.h",
                "tools/esp_iris.py", "tools/requirements.lock", "tools/rpc_catalog.json",
                "tools/iris_gateway/__init__.py", "tools/frontend/dist/index.html",
                "examples/minimal/main/idf_component.yml", "examples/minimal/idf_ext.py"}
    missing = required - files.keys()
    if missing:
        raise ValueError(f"Missing package files: {', '.join(sorted(missing))}")
    yaml = YAML(typ="safe")
    manifest = yaml.load(files["idf_component.yml"])
    version = str(manifest["version"])
    if tag and tag != "esp-iris-v" + version:
        raise ValueError(f"Release tag {tag} does not match component version {version}")
    host = ast.parse(files["tools/iris_gateway/__init__.py"])
    versions = [ast.literal_eval(node.value) for node in host.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
    if versions != [version]:
        raise ValueError("Gateway version does not match component version")
    for name in ("tools/frontend/package.json", "tools/frontend/package-lock.json"):
        data = json.loads(files[name])
        if data.get("version") != version or data.get("packages", {}).get("", {}).get("version", version) != version:
            raise ValueError(f"Workbench version mismatch: {name}")
    for name, data in files.items():
        if name.startswith("examples/") and name.endswith("/main/idf_component.yml"):
            dependencies = yaml.load(data).get("dependencies", {})
            if "espressif/esp_iris" not in dependencies:
                raise ValueError(f"Example does not depend on espressif/esp_iris: {name}")
    assets = Assets()
    assets.feed(files["tools/frontend/dist/index.html"].decode())
    if not assets.paths or any("tools/frontend/dist/" + name not in files for name in assets.paths):
        raise ValueError("Workbench entry references missing assets")
    return files, version


def prepare_consumer(files: dict[str, bytes], work: Path) -> tuple[Path, Path]:
    project = work / "minimal"
    component = project / "managed_components/espressif__esp_iris"
    # Keep existing build directories reusable. Replace only files owned by the
    # package; do not allow files removed from a later archive to survive.
    if component.exists():
        shutil.rmtree(component)
    for name, data in files.items():
        path = component / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    shutil.copytree(component / "examples/minimal", project, dirs_exist_ok=True)
    manifest = project / "main/idf_component.yml"
    yaml = YAML()
    data = yaml.load(manifest)
    # Resolve the unpublished version exclusively from this archive.
    data["dependencies"]["espressif/esp_iris"]["override_path"] = "../managed_components/espressif__esp_iris"
    with manifest.open("w") as stream:
        yaml.dump(data, stream)
    return project, component


def prepare_registry_consumer(work: Path, version: str, registry_url: str) -> tuple[Path, Path]:
    project = work / "minimal"
    if project.exists():
        raise ValueError("Registry verification requires a new work directory")
    env = dict(os.environ)
    # Download anonymously from the selected registry, without local mirrors.
    for name in ("IDF_COMPONENT_API_TOKEN", "IDF_COMPONENT_STORAGE_URL", "IDF_COMPONENT_LOCAL_STORAGE_URL"):
        env.pop(name, None)
    env.update(IDF_COMPONENT_REGISTRY_URL=registry_url, IDF_COMPONENT_PROFILE="default",
               IDF_TOOLS_PATH=str(work / "registry-config"))
    subprocess.run([
        sys.executable, "-c", "from idf_component_manager.cli import safe_cli; safe_cli()",
        "project", "create-from-example",
        f"espressif/esp_iris={version}:minimal", "--path", str(project),
    ], check=True, cwd=work, env=env)
    manifest = project / "main/idf_component.yml"
    yaml = YAML()
    data = yaml.load(manifest)
    dependency = data["dependencies"]["espressif/esp_iris"]
    if isinstance(dependency, str):
        dependency = {"version": dependency}
        data["dependencies"]["espressif/esp_iris"] = dependency
    if any(key in dependency for key in ("override_path", "path", "git")):
        raise ValueError("Downloaded example still depends on a local or Git component")
    # Only Iris comes from staging; SDK dependencies retain their normal registry.
    dependency.update(version="=" + version, registry_url=registry_url)
    with manifest.open("w") as stream:
        yaml.dump(data, stream)
    return project, project / "managed_components/espressif__esp_iris"


def check_installed_component(files: dict[str, bytes], component: Path, version: str) -> None:
    yaml = YAML(typ="safe")
    manifest = yaml.load(component / "idf_component.yml")
    if str(manifest["version"]) != version:
        raise ValueError("Installed component version does not match the archive")
    if manifest != yaml.load(files["idf_component.yml"]):
        raise ValueError("Installed component manifest differs from the archive")
    for name, expected in files.items():
        # Registry processing can normalize manifest serialization.
        if name == "idf_component.yml":
            continue
        path = component / name
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError(f"Installed component differs from the archive: {name}")


def check_host(component: Path, work: Path, version: str) -> None:
    # A separate interpreter prevents imports from the checkout hiding missing
    # package files. No discovery loop or physical device is started.
    probe = r'''
import asyncio, hashlib, importlib.util, sys
from pathlib import Path
component, work, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(component / "tools"))
from aiohttp.test_utils import TestClient, TestServer
from iris_gateway import __version__
from iris_gateway.gateway import GatewayService, create_app
from iris_gateway.store import GatewayStore
from iris_gateway.source_identity import running_source, source_identity
assert __version__ == version
identity = running_source()
assert identity["fingerprint"] != hashlib.sha256(b"").hexdigest()
assert identity == source_identity(component)
spec = importlib.util.spec_from_file_location("sample_extension", component.parents[1] / "idf_ext.py")
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)
extension.action_extensions({"actions": {}}, str(component.parents[1]))
import iris_usb_flash
Path(iris_usb_flash.__file__).relative_to(component)
async def check():
    store = GatewayStore(work / "gateway-state")
    service = GatewayService(store, instance_id="package-check", frontend_dist=component / "tools/frontend/dist")
    client = TestClient(TestServer(create_app(service)))
    await client.start_server()
    try:
        response = await client.get("/")
        assert response.status == 200
        assert await response.read() == (component / "tools/frontend/dist/index.html").read_bytes()
        for asset in (component / "tools/frontend/dist/assets").iterdir():
            if asset.is_file():
                response = await client.get("/assets/" + asset.name)
                assert response.status == 200 and await response.read() == asset.read_bytes()
    finally:
        await client.close()
        store.close()
asyncio.run(check())
'''
    subprocess.run([sys.executable, "-I", "-c", probe, str(component), str(work), version], check=True, cwd=work)


def build_consumer(project: Path, target: str, transport: str) -> None:
    idf = Path(os.environ["IDF_PATH"])
    defaults = project / "sdkconfig.package.defaults"
    options = ["CONFIG_IDF_EXPERIMENTAL_FEATURES=y", "CONFIG_ESPTOOLPY_FLASHSIZE_2MB=y",
               "CONFIG_ESP_IRIS_FIRMWARE_ROLE=1"]
    names = {"usj": "USB_SERIAL_JTAG", "usb": "USB", "uart": "UART", "tcp": "TCP"}
    options.append(f"CONFIG_ESP_IRIS_TRANSPORT_{names[transport]}=y")
    if transport == "usj":
        options += ["CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y", "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y"]
    if transport == "usb":
        options += ["CONFIG_TINYUSB_CDC_COUNT=2", "CONFIG_ESP_IRIS_USB_AUTO_DOWNLOAD=y"]
    defaults.write_text("\n".join(options) + "\n")
    subprocess.run([sys.executable, str(idf / "tools/idf.py"), "-C", str(project),
                    "-B", str(project / "build"), "-D", f"IDF_TARGET={target}",
                    "-D", f"SDKCONFIG_DEFAULTS={defaults}", "-D", f"ESP_IRIS_BUILD_PROFILE={transport}",
                    "build"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--registry-url", help="Download and build the published minimal example; requires --build")
    parser.add_argument("--target", default="esp32h2")
    parser.add_argument("--transport", choices=("usj", "usb", "uart", "tcp"), default="usj")
    args = parser.parse_args()
    if args.registry_url and not args.build:
        parser.error("--registry-url requires --build to resolve the managed component")
    files, version = validate_archive(args.archive, args.tag)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args.registry_url:
        project, component = prepare_registry_consumer(work, version, args.registry_url)
        build_consumer(project, args.target, args.transport)
        check_installed_component(files, component, version)
        check_host(component, work, version)
    else:
        project, component = prepare_consumer(files, work)
        check_host(component, work, version)
        if args.build:
            build_consumer(project, args.target, args.transport)
    print(f"ESP-Iris {version}: {len(files)} package files validated; isolated consumer checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
