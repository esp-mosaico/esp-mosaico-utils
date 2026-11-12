"""Fresh builds must prepare their Board without a failed application configure."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mosaico_cli import raylib_bmgr as bmgr, runtime
from mosaico_cli.errors import BuildError, EnvironmentError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "game with spaces"
    source.mkdir()
    engine = tmp_path / "tools"
    profile = engine / "examples/boards/esp-mosaico/bmgr"
    (profile / bmgr.BOARD).mkdir(parents=True)
    (profile / bmgr.BOARD / "board_info.yaml").write_text("board: esp_mosaico\n")
    calls = []
    context = SimpleNamespace(directory=tmp_path / "run", workspace=SimpleNamespace(),
                              log_path=tmp_path / "log", status=lambda message: None)
    def configure(ctx, **kwargs):
        calls.append(("configure", kwargs))
        plugin = kwargs["project"] / "managed_components/espressif__esp_board_manager"
        plugin.mkdir(parents=True)
        (plugin / "idf_ext.py").touch()
    def command(ctx, **kwargs):
        return {"argv": ["idf.py", "-C", str(kwargs["project"]), "bmgr"], "env": {}, "cwd": str(tmp_path)}
    def generate(argv, **kwargs):
        calls.append(("generate", argv, kwargs))
        project = Path(argv[argv.index("-C") + 1])
        board = Path(argv[argv.index("-c") + 1]) / bmgr.BOARD
        generated = project / "components/gen_bmgr_codes"
        write_generated(generated, board)
        return SimpleNamespace(returncode=0)
    context.run = generate
    monkeypatch.setattr(runtime, "resolve_idf_path", lambda *args: tmp_path / "idf")
    monkeypatch.setattr(runtime, "run_idf_target", configure)
    monkeypatch.setattr(runtime, "idf_target_command", command)
    return context, source, engine, profile, calls


def write_generated(component, board):
    component.mkdir(parents=True)
    for name in bmgr.GENERATED_FILES:
        (component / name).write_text("generated\n")
    (component / "gen_board_metadata.yaml").write_text(
        f"board: esp_mosaico\nchip: esp32s31\nboard_path: {board.as_posix()}\n")
    relative = Path(os.path.relpath(board, component)).as_posix()
    (component / "CMakeLists.txt").write_text(f'idf_component_register(SRC_DIRS "." "{relative}")\n')


def test_clean_project_prepares_and_relocates_without_touching_sdkconfig(setup):
    context, source, engine, profile, calls = setup
    (source / "sdkconfig").write_text("user settings\n")
    bmgr.prepare_board(context, source, source, engine)
    component = source / "components/gen_bmgr_codes"
    relative = Path(os.path.relpath(profile / bmgr.BOARD, component)).as_posix()
    assert f'"{relative}"' in (component / "CMakeLists.txt").read_text()
    assert (source / "sdkconfig").read_text() == "user settings\n"
    assert not (source / "managed_components").exists()
    assert calls[0][1]["project"] != source
    assert calls[1][2]["env"]["IDF_EXTRA_ACTIONS_PATH"].endswith("espressif__esp_board_manager")
    bmgr.prepare_board(context, source, source, engine)
    assert len(calls) == 2  # Existing config works offline; no SDK/download work.


def test_iris_wrapper_uses_registry_board_and_preserves_native_board(setup):
    context, source, engine, _, calls = setup
    launcher = source / "shared/common_components/examples_common/project.cmake"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    profile = source / "shared/boards/esp-mosaico/bmgr"
    (profile / bmgr.BOARD).mkdir(parents=True)
    (profile / bmgr.BOARD / "board_info.yaml").touch()
    original = source / "components/gen_bmgr_codes/gen_board_metadata.yaml"
    original.parent.mkdir(parents=True)
    original.write_text("board: another_board\n")
    wrapper = source.parent / "wrapper"
    wrapper.mkdir()
    bmgr.prepare_board(context, wrapper, source, engine)
    assert calls[1][1][-4:] == ["-c", str(profile.resolve()), "-b", bmgr.BOARD]
    assert original.read_text() == "board: another_board\n"
    assert (wrapper / "components/gen_bmgr_codes/gen_board_device_custom.h").is_file()


def test_missing_registry_profile_never_falls_back_to_engine(setup):
    context, source, engine, _, calls = setup
    launcher = source / "shared/common_components/examples_common/project.cmake"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    with pytest.raises(EnvironmentError, match="profile is missing"):
        bmgr.prepare_board(context, source, source, engine)
    assert not calls


@pytest.mark.parametrize("failure", ["exit", "timeout", "incomplete"])
def test_failed_generation_does_not_publish_or_edit_project(setup, failure):
    import subprocess
    context, source, engine, _, _ = setup
    def fail(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("bmgr", 300)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0)
    context.run = fail
    with pytest.raises((BuildError, EnvironmentError)):
        bmgr.prepare_board(context, source, source, engine)
    assert list(source.iterdir()) == []


def test_existing_wrong_board_is_preserved_and_rejected_for_product(setup):
    context, source, engine, profile, calls = setup
    component = source / "components/gen_bmgr_codes"
    write_generated(component, profile / bmgr.BOARD)
    metadata = component / "gen_board_metadata.yaml"
    metadata.write_text("board: another_board\n")
    with pytest.raises(EnvironmentError, match="another Board"):
        bmgr.prepare_board(context, source, source, engine)
    assert metadata.read_text() == "board: another_board\n"
    assert not calls
    bmgr.prepare_board(context, source, source, engine, product=False)
    assert not calls


def test_application_build_prepares_wrapper_from_recorded_source(setup, monkeypatch):
    from mosaico_cli import raylib_toolchain
    context, source, engine, _, _ = setup
    wrapper = source.parent / "wrapper"
    wrapper.mkdir()
    (wrapper / "CMakeLists.txt").write_text('include("raylib_lite_iris_app.cmake")\n')
    (wrapper / ".mosaico-game-source.json").write_text(json.dumps({"source": str(source)}))
    runner = source.parent / "runner.py"
    runner.touch()
    context.workspace.build_runner = runner
    context.workspace.configdep = "auto"
    context.workspace.root = source.parent
    prepared = []
    monkeypatch.setattr(raylib_toolchain, "ensure_toolchain", lambda workspace: engine)
    monkeypatch.setattr(bmgr, "prepare_board", lambda *args: prepared.append(args))
    context.run = lambda *args, **kwargs: SimpleNamespace(returncode=0)
    runtime.build_application(context, wrapper)
    assert prepared == [(context, wrapper, source, engine)]


@pytest.mark.skipif(shutil.which("cmake") is None, reason="Wrapper configuration needs CMake")
def test_wrapper_cmake_excludes_native_generated_board(tmp_path):
    """Configure the real helper with a native component that must never load."""
    import subprocess
    tools = tmp_path / "utils/mosaico-tools"
    cmake_dir = tools / "cmake"
    cmake_dir.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / "cmake/raylib_lite_iris_app.cmake"
    shutil.copyfile(original, cmake_dir / original.name)
    (tools / "templates/blank_game").mkdir(parents=True)
    recovery = tools.parent / "esp-mosaico-vibe-mode/cmake/mosaico_idf_project.cmake"
    recovery.parent.mkdir(parents=True)
    recovery.touch()
    (cmake_dir / "mosaico_idf_project.cmake").touch()
    engine = tmp_path / "engine"
    header = engine / "include/raylib_lite/raylib_lite_native_services.h"
    header.parent.mkdir(parents=True)
    header.touch()
    common = engine / "examples/common_components/examples_common/project.cmake"
    common.parent.mkdir(parents=True)
    common.touch()
    source = tmp_path / "source"
    for name in ("main", "components/gen_bmgr_codes", "components/game_logic"):
        folder = source / name
        folder.mkdir(parents=True)
        (folder / "CMakeLists.txt").touch()
    project = tmp_path / "wrapper"
    project.mkdir()
    (project / "partitions.csv").touch()
    (project / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.22)\n'
        f'set(RAYLIB_LITE_ENGINE_ROOT "{engine.as_posix()}")\n'
        f'set(RAYLIB_LITE_GAME_DIR "{source.as_posix()}")\n'
        f'include("{(cmake_dir / original.name).as_posix()}")\n'
        'project(wrapper NONE)\n'
        'file(WRITE "${CMAKE_BINARY_DIR}/components.txt" "${EXTRA_COMPONENT_DIRS}")\n')
    subprocess.run(["cmake", "-S", str(project), "-B", str(project / "build")],
                   check=True, capture_output=True, text=True)
    components = (project / "build/components.txt").read_text().split(";")
    assert (source / "main").as_posix() in components
    assert (source / "components/game_logic").as_posix() in components
    assert (source / "components/gen_bmgr_codes").as_posix() not in components
    assert (source / "components").as_posix() not in components
