from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from iris_gateway import crash_diagnostics


def test_decode_coredump_confirms_source_and_failed_boot(
    tmp_path: Path, monkeypatch
) -> None:
    idf = tmp_path / "idf"
    script = idf / "components" / "espcoredump" / "espcoredump.py"
    script.parent.mkdir(parents=True)
    script.write_text("# decoder\n", encoding="utf-8")
    python = tmp_path / "python"
    interpreter = tmp_path / "interpreter"
    interpreter.write_text("", encoding="utf-8")
    try:
        python.symlink_to(interpreter)
    except OSError:
        python.write_text("", encoding="utf-8")
    elf_dir = tmp_path / "firmware"
    elf_dir.mkdir()
    (elf_dir / "firmware.elf").write_bytes(b"elf")
    core = tmp_path / "core.bin"
    core.write_bytes(b"core")
    monkeypatch.setenv("ESP_IRIS_IDF_PATH", str(idf))
    monkeypatch.setenv("ESP_IRIS_IDF_PYTHON", str(python))
    monkeypatch.setenv("ESP_IRIS_GDB", "riscv32-esp-elf-gdb")
    monkeypatch.setattr(crash_diagnostics.shutil, "which", lambda value: value)

    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert command[0] == str(python.absolute())
            Path(command[command.index("--save-core") + 1]).write_bytes(b"core-elf")
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "Panic reason: Store access fault\n"
                    "Crashed task handle: 0x1, name: 'fault-task'\n"
                    "#0  0x40001234 in trigger_fault () at /workspace/main/crash.c:42\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="IRIS_CONTEXT_BOOT=77\n")

    monkeypatch.setattr(crash_diagnostics.subprocess, "run", run)
    diagnosis, raw = crash_diagnostics.decode_coredump(
        core,
        {"path": str(elf_dir), "files": {"firmware.elf": "firmware.elf"}},
        expected_failed_boot_id=77,
    )

    assert diagnosis["status"] == "succeeded"
    assert diagnosis["panic_reason"] == "Store access fault"
    assert diagnosis["crashed_task"] == "fault-task"
    assert diagnosis["source_location"] == {
        "index": 0,
        "function": "trigger_fault",
        "file": "/workspace/main/crash.c",
        "line": 42,
    }
    assert diagnosis["incident_identity_confirmed"] is True
    assert b"IRIS_CONTEXT_BOOT=77" in raw


def test_decode_coredump_rejects_another_boot(
    tmp_path: Path, monkeypatch
) -> None:
    idf = tmp_path / "idf"
    script = idf / "components" / "espcoredump" / "espcoredump.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    elf_dir = tmp_path / "firmware"
    elf_dir.mkdir()
    (elf_dir / "firmware.elf").write_bytes(b"elf")
    monkeypatch.setenv("ESP_IRIS_IDF_PATH", str(idf))
    monkeypatch.setenv("ESP_IRIS_IDF_PYTHON", str(python))
    monkeypatch.setenv("ESP_IRIS_GDB", "gdb")
    monkeypatch.setattr(crash_diagnostics.shutil, "which", lambda value: value)

    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(command[command.index("--save-core") + 1]).write_bytes(b"core-elf")
            return SimpleNamespace(returncode=0, stdout="#0  fault ()\n")
        return SimpleNamespace(returncode=0, stdout="IRIS_CONTEXT_BOOT=76\n")

    monkeypatch.setattr(crash_diagnostics.subprocess, "run", run)
    diagnosis, _ = crash_diagnostics.decode_coredump(
        tmp_path / "core.bin",
        {"path": str(elf_dir)},
        expected_failed_boot_id=77,
    )

    assert diagnosis["status"] == "succeeded"
    assert diagnosis["incident_identity_confirmed"] is False
    assert "does not match" in diagnosis["reason"]


def test_decode_coredump_does_not_claim_idf_frame_as_app_source(
    tmp_path: Path, monkeypatch
) -> None:
    idf = tmp_path / "esp-idf-current"
    script = idf / "components" / "espcoredump" / "espcoredump.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    elf_dir = tmp_path / "firmware"
    elf_dir.mkdir()
    (elf_dir / "firmware.elf").write_bytes(b"elf")
    monkeypatch.setenv("ESP_IRIS_IDF_PATH", str(idf))
    monkeypatch.setenv("ESP_IRIS_IDF_PYTHON", str(python))
    monkeypatch.setenv("ESP_IRIS_GDB", "gdb")

    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(command[command.index("--save-core") + 1]).write_bytes(b"core")
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f"#0  panic_abort () at {idf}/components/panic.c:10\n"
                    "#1  app_fault () at /workspace/main/crash.c:42\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="IRIS_CONTEXT_BOOT=77\n")

    monkeypatch.setattr(crash_diagnostics.shutil, "which", lambda value: value)
    monkeypatch.setattr(crash_diagnostics.subprocess, "run", run)
    diagnosis, _ = crash_diagnostics.decode_coredump(
        tmp_path / "core.bin",
        {"path": str(elf_dir)},
        expected_failed_boot_id=77,
    )

    assert diagnosis["source_location"]["function"] == "app_fault"
