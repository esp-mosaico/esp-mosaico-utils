#!/usr/bin/env python3
"""Validate the release archive and exercise an isolated component installation."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

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
    forbidden = {".codex-runs", "node_modules", "__pycache__", "managed_components", "dev_docs",
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
    required = {"idf_component.yml", "CMakeLists.txt", "Kconfig", "LICENSE", "include/esp_iris.h", "esp_iris.py",
                "tools/esp_iris.py", "tools/requirements.lock", "tools/rpc_catalog.json",
                "tools/iris_gateway/__init__.py", "tools/frontend/dist/index.html",
                "tools/frontend/package.json", "tools/frontend/package-lock.json",
                "README.md", "CHANGELOG.md", "tools/README.md",
                "examples/minimal/main/idf_component.yml", "examples/minimal/idf_ext.py"}
    missing = required - files.keys()
    if missing:
        raise ValueError(f"Missing package files: {', '.join(sorted(missing))}")
    yaml = YAML(typ="safe")
    manifest = yaml.load(files["idf_component.yml"])
    version = str(manifest["version"])
    if not re.search(r"(?m)^## " + re.escape(version) + r"(?:\s|$)", files.get("CHANGELOG.md", b"").decode()):
        raise ValueError("Component version has no changelog entry")
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
        if (name.startswith("tools/frontend/tests/") or
                (name.startswith("tools/frontend/") and re.search(r"\.(test|spec)\.[jt]sx?$", name))):
            raise ValueError(f"Frontend test in runtime package: {name}")
        if name.startswith("examples/") and name.endswith("/main/idf_component.yml"):
            dependencies = yaml.load(data).get("dependencies", {})
            if "espressif/esp_iris" not in dependencies:
                raise ValueError(f"Example does not depend on espressif/esp_iris: {name}")
            example = name.rsplit("/main/", 1)[0]
            for entry in ("README.md", "CMakeLists.txt", "esp_iris.py"):
                if example + "/" + entry not in files:
                    raise ValueError(f"Incomplete standalone example: {example}/{entry}")
        if name.endswith(".md"):
            for link in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", data.decode("utf-8")):
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(parsed.path)))
                if destination not in files and not any(path.startswith(destination.rstrip("/") + "/") for path in files):
                    raise ValueError(f"Broken package documentation link: {name}: {link}")
    assets = Assets()
    assets.feed(files["tools/frontend/dist/index.html"].decode())
    if not assets.paths or any("tools/frontend/dist/" + name not in files for name in assets.paths):
        raise ValueError("Workbench entry references missing assets")
    return files, version


def prepare_consumer(files: dict[str, bytes], work: Path, example: str = "minimal") -> tuple[Path, Path]:
    if f"examples/{example}/main/idf_component.yml" not in files or Path(example).name != example:
        raise ValueError(f"Unknown package example: {example}")
    project = work / example
    component = project / "managed_components/espressif__esp_iris"
    # Keep existing build directories reusable. Replace only files owned by the
    # package; do not allow files removed from a later archive to survive.
    if component.exists():
        shutil.rmtree(component)
    for name, data in files.items():
        path = component / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    shutil.copytree(component / "examples" / example, project, dirs_exist_ok=True)
    manifest = project / "main/idf_component.yml"
    yaml = YAML()
    data = yaml.load(manifest)
    # Resolve the unpublished version exclusively from this archive.
    data["dependencies"]["espressif/esp_iris"]["override_path"] = "../managed_components/espressif__esp_iris"
    with manifest.open("w") as stream:
        yaml.dump(data, stream)
    return project, component


def prepare_registry_consumer(work: Path, version: str, registry_url: str, example: str = "minimal") -> tuple[Path, Path]:
    if Path(example).name != example or example in (".", ".."):
        raise ValueError("Invalid example name")
    project = work / example
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
        f"espressif/esp_iris={version}:{example}", "--path", str(project),
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


def registry_manifest(data: bytes, *, example: bool = False):
    manifest = YAML(typ="safe").load(data)
    for dependency in manifest.get("dependencies", {}).values():
        if not isinstance(dependency, dict):
            continue
        if example:
            dependency.pop("override_path", None)
        if dependency.get("require") in ("no", "yes"):
            dependency["require"] = dependency["require"] == "yes"
    return manifest


def check_installed_component(files: dict[str, bytes], component: Path, version: str) -> None:
    yaml = YAML(typ="safe")
    manifest = yaml.load(component / "idf_component.yml")
    if str(manifest["version"]) != version:
        raise ValueError("Installed component version does not match the archive")
    if registry_manifest((component / "idf_component.yml").read_bytes()) != registry_manifest(files["idf_component.yml"]):
        raise ValueError("Installed component manifest differs from the archive")
    for name, expected in files.items():
        path = component / name
        if not path.is_file():
            raise ValueError(f"Installed component differs from the archive: {name}")
        actual = path.read_bytes()
        if name.endswith("idf_component.yml"):
            # The Registry normalizes YAML and removes source-only example overrides.
            expected_manifest = registry_manifest(expected, example=name.startswith("examples/"))
            if registry_manifest(actual) != expected_manifest:
                raise ValueError(f"Installed component manifest differs from the archive: {name}")
        elif actual != expected:
            raise ValueError(f"Installed component differs from the archive: {name}")


def check_host(component: Path, work: Path, version: str) -> None:
    # A separate interpreter prevents imports from the checkout hiding missing
    # package files. No discovery loop or physical device is started.
    probe = r'''
import asyncio, hashlib, importlib.util, sys
from concurrent.futures import ThreadPoolExecutor
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
if (component.parents[1] / "idf_ext.py").is_file():
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
# Python 3.8's asyncio.run does not join the default executor. FileResponse
# closes files there; finish those callbacks before closing the event loop.
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
with ThreadPoolExecutor() as executor:
    loop.set_default_executor(executor)
    try:
        loop.run_until_complete(check())
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        executor.shutdown(wait=True)
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
'''
    subprocess.run([sys.executable, "-I", "-c", probe, str(component), str(work), version], check=True, cwd=work)


def build_consumer(project: Path, target: str, transport: str, psram: bool = False) -> None:
    idf = Path(os.environ["IDF_PATH"])
    defaults = project / "sdkconfig.package.defaults"
    options = ["CONFIG_IDF_EXPERIMENTAL_FEATURES=y",
               "CONFIG_ESP_IRIS_FIRMWARE_ROLE=1"]
    names = {"usj": "USB_SERIAL_JTAG", "usb": "USB", "uart": "UART", "tcp": "TCP"}
    options.append("CONFIG_ESP_IRIS_ENABLE=" + ("n" if transport == "disabled" else "y"))
    options.extend(f"CONFIG_ESP_IRIS_TRANSPORT_{name}=" + ("y" if key == transport else "n")
                   for key, name in names.items())
    if transport == "usj":
        options += ["CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y", "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y"]
    if transport == "usb":
        options += ["CONFIG_TINYUSB_CDC_COUNT=2", "CONFIG_ESP_IRIS_USB_AUTO_DOWNLOAD=y"]
    if psram:
        if target != "esp32s31" or transport != "usb":
            raise ValueError("PSRAM validation requires S31 application USB")
        options += ["CONFIG_SPIRAM=y", "CONFIG_SPIRAM_XIP_FROM_PSRAM=y",
                    "CONFIG_SPIRAM_ALLOW_BSS_SEG_EXTERNAL_MEMORY=y", "CONFIG_ESP_IRIS_OTA=n",
                    "CONFIG_ESP_IRIS_SYSTEM_UPDATE=n", "CONFIG_ESP_IRIS_WIRE_BUFFERS_PSRAM=y",
                    "CONFIG_ESP_IRIS_USB_FIFO_PSRAM=y"]
    defaults.write_text("\n".join(options) + "\n")
    subprocess.run([sys.executable, str(idf / "tools/idf.py"), "-C", str(project),
                    "-B", str(project / "build"), "-D", f"IDF_TARGET={target}",
                    "-D", f"SDKCONFIG_DEFAULTS=sdkconfig.defaults;{defaults}",
                    "-D", f"ESP_IRIS_BUILD_PROFILE={transport}",
                    "build"], check=True)
    config = (project / "sdkconfig").read_text()
    expected = ("# CONFIG_ESP_IRIS_ENABLE is not set" if transport == "disabled" else
                "CONFIG_ESP_IRIS_TRANSPORT_" + names[transport] + "=y")
    if expected not in config or (psram and "CONFIG_ESP_IRIS_USB_FIFO_PSRAM=y" not in config):
        raise ValueError("SDK silently disabled the requested package validation configuration")
    if psram:
        check_fifo_placement(next((project / "build").glob("*.elf")), config)


def check_fifo_placement(elf: Path, config: str) -> None:
    """Check actual linker placement, including the state that must stay internal."""
    from elftools.elf.elffile import ELFFile

    settings = dict(re.findall(r"(?m)^(CONFIG_\w+)=(\d+)$", config))
    interfaces = int(settings["CONFIG_TINYUSB_CDC_COUNT"])
    with elf.open("rb") as stream:
        binary = ELFFile(stream)
        symbols = {symbol.name: symbol for symbol in binary.get_section_by_name(".symtab").iter_symbols()}
        for direction in ("rx", "tx"):
            symbol = symbols["iris_cdc_" + direction + "_fifo"]
            section = binary.get_section(symbol["st_shndx"]).name
            expected_size = interfaces * int(settings["CONFIG_TINYUSB_CDC_" + direction.upper() + "_BUFSIZE"])
            if section != ".ext_ram.bss" or symbol["st_size"] != expected_size:
                raise ValueError("CDC FIFO placement or capacity does not match the PSRAM configuration")
        for name in ("_cdcd_itf", "_cdcd_epbuf"):
            section = binary.get_section(symbols[name]["st_shndx"]).name
            if not section.startswith(".dram"):
                raise ValueError("CDC stream/mutex/DMA state must remain in internal RAM")


def package_fingerprint(files: dict[str, bytes]) -> str:
    """Identify exact package contents independently of tar timestamps/compression."""
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--example", default="minimal")
    parser.add_argument("--psram", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--registry-url", help="Download and build the selected published example; requires --build")
    parser.add_argument("--target", default="esp32h2")
    parser.add_argument("--transport", choices=("usj", "usb", "uart", "tcp", "disabled"), default="usj")
    args = parser.parse_args()
    if args.registry_url and not args.build:
        parser.error("--registry-url requires --build to resolve the managed component")
    if args.psram and not args.build:
        parser.error("--psram requires --build to verify linker placement")
    files, version = validate_archive(args.archive, args.tag)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args.registry_url:
        project, component = prepare_registry_consumer(work, version, args.registry_url, args.example)
        build_consumer(project, args.target, args.transport, args.psram)
        check_installed_component(files, component, version)
        check_host(component, work, version)
    else:
        project, component = prepare_consumer(files, work, args.example)
        check_host(component, work, version)
        if args.build:
            build_consumer(project, args.target, args.transport, args.psram)
    if args.report:
        report = {"schema": "esp-iris-package-check/v1", "version": version,
                  "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                  "package_fingerprint": package_fingerprint(files),
                  "source_commit": os.environ.get("CI_COMMIT_SHA", os.environ.get("GITHUB_SHA", "")),
                  "pipeline_url": os.environ.get("CI_PIPELINE_URL", ""),
                  "python": sys.version.split()[0], "platform": sys.platform,
                  "example": args.example, "build": args.build, "target": args.target,
                  "transport": args.transport, "psram": args.psram,
                  "registry_url": args.registry_url, "result": "passed",
                  "hardware_validation": "not_performed"}
        if args.build:
            report["idf_commit"] = subprocess.check_output(
                ["git", "-C", os.environ["IDF_PATH"], "rev-parse", "HEAD"], text=True).strip()
            report["idf_dirty"] = bool(subprocess.check_output(
                ["git", "-C", os.environ["IDF_PATH"], "status", "--porcelain", "--untracked-files=no"], text=True).strip())
            report["sdkconfig_sha256"] = hashlib.sha256((project / "sdkconfig").read_bytes()).hexdigest()
            dependencies = YAML(typ="safe").load(project / "dependencies.lock")["dependencies"]
            report["dependencies"] = {name: {key: entry[key] for key in ("version", "component_hash") if key in entry}
                                      for name, entry in dependencies.items()}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"ESP-Iris {version}: {len(files)} package files validated; isolated consumer checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
