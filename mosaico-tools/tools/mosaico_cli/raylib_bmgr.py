"""Prepare a game's Board Manager component before IDF resolves its dependencies.

Generation runs in a tools-owned bootstrap project. Only the completed component
is published to the application; the generator never edits application sdkconfig.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .errors import BuildError, EnvironmentError

BOARD = "esp_mosaico"
GENERATOR_VERSION = "0.7.5"
GENERATED_FILES = (
    "CMakeLists.txt", "idf_component.yml", "gen_board_metadata.yaml",
    "board_manager.defaults", "gen_board_device_custom.h",
    "gen_board_device_config.c", "gen_board_periph_config.c",
)


def board_profile(source: Path, engine: Path) -> Path:
    # A published example owns its launcher and Board together. Never silently
    # replace a missing example Board with the blank game's Engine Board.
    if (source / "shared/common_components/examples_common/project.cmake").is_file():
        profile = source / "shared/boards/esp-mosaico/bmgr"
    else:
        profile = engine / "examples/boards/esp-mosaico/bmgr"
    if not (profile / BOARD / "board_info.yaml").is_file():
        raise EnvironmentError(f"Raylib Board Manager profile is missing: {profile}")
    return profile.resolve()


def _metadata(path: Path, key: str) -> str:
    match = re.search(r"(?m)^" + key + r":\s*([^\r\n]+)",
                      path.read_text(encoding="utf-8"))
    return match.group(1).strip().strip("\"'") if match else ""


def _validate(component: Path, board_dir: Path) -> None:
    if not all((component / name).is_file() for name in GENERATED_FILES):
        raise EnvironmentError(f"Incomplete Raylib Board Manager configuration: {component}. "
                               "Preserve it outside components/ before retrying the build.")
    metadata = component / "gen_board_metadata.yaml"
    if (_metadata(metadata, "board") != BOARD or
            _metadata(metadata, "chip") != "esp32s31" or
            Path(_metadata(metadata, "board_path")).resolve() != board_dir):
        raise EnvironmentError(f"Raylib Board Manager configuration selects another Board or source: {metadata}. "
                               "Preserve it outside components/ before retrying the product build.")


def prepare_board(context, project: Path, source: Path, engine: Path, *, product: bool = True) -> None:
    """Generate missing esp_mosaico config without overwriting existing config."""
    from .runtime import idf_target_command, resolve_idf_path, run_idf_target

    profile = board_profile(source, engine)
    board_dir = profile / BOARD
    component = project / "components/gen_bmgr_codes"
    if component.exists():
        # Native builds retain the source project's explicit Board selection.
        if (not product and (component / "CMakeLists.txt").is_file()
                and (component / "gen_board_metadata.yaml").is_file()):
            return
        _validate(component, board_dir)
        return

    # The real project cannot reconfigure yet: its Board requires the generated
    # component. Resolve only the generator in a separate minimal IDF project.
    bootstrap = context.directory / "bmgr-bootstrap" / project.name
    main = bootstrap / "main"
    main.mkdir(parents=True)
    (bootstrap / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.22)\n'
        'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n'
        'project(mosaico_bmgr_bootstrap)\n', encoding="utf-8")
    (bootstrap / "sdkconfig.defaults").write_text(
        'CONFIG_IDF_TARGET="esp32s31"\nCONFIG_IDF_EXPERIMENTAL_FEATURES=y\n', encoding="utf-8")
    (main / "CMakeLists.txt").write_text('idf_component_register()\n', encoding="utf-8")
    (main / "idf_component.yml").write_text(
        'dependencies:\n  espressif/esp_board_manager: "==' + GENERATOR_VERSION + '"\n', encoding="utf-8")
    idf_path = resolve_idf_path(context.workspace, project)
    context.status("game: preparing Board Manager generator")
    run_idf_target(context, idf_path=idf_path, project=bootstrap,
                   build_dir=bootstrap / "build", target="reconfigure", timeout=900)
    plugin = bootstrap / "managed_components/espressif__esp_board_manager"
    if not (plugin / "idf_ext.py").is_file():
        raise EnvironmentError(f"Board Manager action extension is missing: {plugin}")
    command = idf_target_command(context, idf_path=idf_path, project=bootstrap,
                                 build_dir=bootstrap / "build", target="bmgr", timeout=300)
    # Explicit loading works on Linux, Windows and macOS without a global
    # esp-bmgr-assist installation or prior failed application configuration.
    command["env"]["IDF_EXTRA_ACTIONS_PATH"] = str(plugin)
    context.status(f"game: generating {BOARD} from {profile}")
    try:
        result = context.run([*command["argv"], "-c", str(profile), "-b", BOARD],
                             cwd=Path(command["cwd"]), env=command["env"], timeout=300)
    except subprocess.TimeoutExpired as error:
        raise BuildError("Board Manager generation timed out.", details={"log": str(context.log_path)}) from error
    if result.returncode:
        raise BuildError("Board Manager generation failed.", details={"log": str(context.log_path)})
    generated = bootstrap / "components/gen_bmgr_codes"
    _validate(generated, board_dir)
    # BMGR emits paths relative to its output component. Relocate those paths
    # when publishing; do not copy application build/lock/sdkconfig state.
    relative = Path(os.path.relpath(board_dir, generated)).as_posix()
    try:
        destination_relative = Path(os.path.relpath(board_dir, component)).as_posix()
    except ValueError:  # Windows application on a different drive.
        destination_relative = board_dir.as_posix()
    cmake = generated / "CMakeLists.txt"
    cmake.write_text(cmake.read_text(encoding="utf-8").replace(
        '"' + relative + '"', '"' + destination_relative + '"'), encoding="utf-8")
    component.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bmgr-", dir=component.parent) as temporary:
        staged = Path(temporary) / "gen_bmgr_codes"
        shutil.copytree(generated, staged)
        # A competing preparation may have completed while IDF was running.
        if component.exists():
            _validate(component, board_dir)
        else:
            staged.rename(component)
