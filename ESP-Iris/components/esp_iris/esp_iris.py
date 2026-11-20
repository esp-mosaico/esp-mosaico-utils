#!/usr/bin/env python3
"""Set up and launch the bundled Gateway without changing the IDF environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

COMPONENT = Path(__file__).resolve().parent
LOCK = COMPONENT / "tools/requirements.lock"


def environment_path() -> Path:
    if os.name == "nt":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        cache = Path.home() / "Library/Caches"
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    identity = hashlib.sha256(LOCK.read_bytes()).hexdigest()[:16]
    return cache / "esp-iris" / f"python{sys.version_info.major}.{sys.version_info.minor}-{identity}"


def interpreter(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def setup(environment: Path) -> int:
    if environment.exists() and not (environment / "pyvenv.cfg").is_file():
        raise ValueError("Refusing to overwrite a directory that is not a Python virtual environment")
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = interpreter(environment)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(LOCK)], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    (environment / "esp-iris-requirements.sha256").write_text(
        hashlib.sha256(LOCK.read_bytes()).hexdigest(), encoding="ascii")
    print("ESP-Iris environment ready: " + str(environment))
    return 0


def environment_ready(environment: Path) -> bool:
    marker = environment / "esp-iris-requirements.sha256"
    return (interpreter(environment).is_file() and marker.is_file()
            and marker.read_text(encoding="ascii") == hashlib.sha256(LOCK.read_bytes()).hexdigest())


def doctor(environment: Path, arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only Gateway environment diagnostics")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--port", type=int, help="Check availability of a loopback HTTP port")
    parser.add_argument("--serial", type=Path, help="Check POSIX permissions without opening the device")
    args = parser.parse_args(arguments)
    report = {"python": sys.version.split()[0], "platform": sys.platform,
              "environment": str(environment), "environment_ready": environment_ready(environment),
              "frontend_present": (COMPONENT / "tools/frontend/dist/index.html").is_file()}
    ready = report["environment_ready"] and report["frontend_present"]
    if report["environment_ready"]:
        result = subprocess.run([str(interpreter(environment)), str(COMPONENT / "tools/esp_iris.py"),
                                 "doctor", "--json"], capture_output=True, text=True, check=False)
        report["gateway_imports_ok"] = result.returncode == 0
        ready = ready and result.returncode == 0
        if result.returncode == 0:
            report["gateway"] = json.loads(result.stdout)
        else:
            report["remedy"] = "Run setup to repair the Gateway environment"
    else:
        report["remedy"] = "Run setup using this launcher before starting the Gateway"
    if args.serial:
        available = args.serial.exists() and os.access(args.serial, os.R_OK | os.W_OK)
        report["serial_accessible"] = available
        ready = ready and available
    if args.port is not None:
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", args.port))
                report["port_available"] = True
            except OSError:
                report["port_available"] = False
                ready = False
    report["ready"] = bool(ready)
    print(json.dumps(report, indent=2))
    return 0 if ready else 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--venv", type=Path)
    options, remaining = parser.parse_known_args(arguments)
    environment = options.venv.expanduser().resolve() if options.venv else environment_path()
    if not remaining or remaining[0] in ("-h", "--help"):
        print("Usage: python esp_iris.py [--venv PATH] setup|doctor|web|ctl ...\n"
              "setup installs the locked dependencies into an isolated environment.\n"
              "doctor [--json] [--port PORT] [--serial PATH] checks local readiness.\n"
              "Other commands are forwarded unchanged to the bundled Gateway.")
        return 0
    if remaining[0] == "setup":
        if len(remaining) != 1:
            parser.error("setup only accepts --venv PATH")
        return setup(environment)
    if remaining[0] == "doctor":
        return doctor(environment, remaining[1:])
    if not environment_ready(environment):
        print("ESP-Iris dependencies are not installed for this package. Run this launcher with setup.",
              file=sys.stderr)
        return 1
    return subprocess.call([str(interpreter(environment)), str(COMPONENT / "tools/esp_iris.py"), *remaining])


def cli() -> int:
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("ESP-Iris: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
