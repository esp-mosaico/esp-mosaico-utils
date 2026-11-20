"""Package launch diagnostics work before runtime dependencies are installed."""
import importlib.util
import json
import socket
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("launcher", Path(__file__).resolve().parents[2] / "esp_iris.py")
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


def test_setup_preserves_an_unrelated_directory(tmp_path):
    marker = tmp_path / "keep"
    marker.write_text("user data")
    with pytest.raises(ValueError, match="Refusing"):
        LAUNCHER.setup(tmp_path)
    assert marker.read_text() == "user data"


def test_doctor_reports_missing_setup_without_installing(tmp_path, capsys):
    assert LAUNCHER.doctor(tmp_path / "absent", ["--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["environment_ready"]
    assert "setup" in report["remedy"]
    assert not (tmp_path / "absent").exists()


def test_doctor_reports_occupied_port_and_missing_serial(tmp_path, capsys):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        assert LAUNCHER.doctor(tmp_path, ["--port", str(server.getsockname()[1]),
                                         "--serial", str(tmp_path / "missing")]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["port_available"] is False
    assert report["serial_accessible"] is False


def test_launcher_preserves_gateway_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(LAUNCHER, "environment_ready", lambda _: True)
    calls = []
    monkeypatch.setattr(LAUNCHER.subprocess, "call", lambda argv: calls.append(argv) or 7)
    arguments = ["web", "--port", "8444", "--state-dir", "directory with spaces"]
    assert LAUNCHER.main(["--venv", str(tmp_path), *arguments]) == 7
    assert calls[0][2:] == arguments
    assert calls[0][0] == str(LAUNCHER.interpreter(tmp_path))


def test_lock_change_requires_setup(tmp_path, monkeypatch):
    lock = tmp_path / "requirements.lock"
    lock.write_text("first lock")
    monkeypatch.setattr(LAUNCHER, "LOCK", lock)
    monkeypatch.setattr(LAUNCHER, "interpreter", lambda _: lock)
    marker = tmp_path / "esp-iris-requirements.sha256"
    marker.write_text(LAUNCHER.hashlib.sha256(lock.read_bytes()).hexdigest())
    assert LAUNCHER.environment_ready(tmp_path)
    lock.write_text("updated lock")
    assert not LAUNCHER.environment_ready(tmp_path)


@pytest.mark.parametrize("error,code", [(KeyboardInterrupt(), 130), (OSError("Cannot create environment"), 1)])
def test_launcher_reports_startup_failures_without_traceback(monkeypatch, capsys, error, code):
    def fail():
        raise error

    monkeypatch.setattr(LAUNCHER, "main", fail)
    assert LAUNCHER.cli() == code
    assert "Traceback" not in capsys.readouterr().err
