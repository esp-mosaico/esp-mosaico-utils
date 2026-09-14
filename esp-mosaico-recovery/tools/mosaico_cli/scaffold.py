"""Create normal applications from the consuming workspace's reference project.

This command uses only the standard library. It does not prepare ESP-IDF or
ESP-Iris host environments, start a Gateway, or require a connected device.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

from .errors import EnvironmentError, OperationError, SelectionError
from .workspace import WorkspaceConfig


TEMPLATE_FILES = (
    "CMakeLists.txt",
    "README.md",
    "partitions.csv",
    "sdkconfig.defaults",
    "sdkconfig.application.defaults",
    "main/CMakeLists.txt",
    "main/idf_component.yml",
    "main/main.c",
)
_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def _inside(path: Path, parent: Path) -> bool:
    return parent in path.parents


def _replace_once(text: str, pattern: str, replacement: str, field: str) -> str:
    # A callable replacement keeps CMake and YAML escapes literal.
    rendered, count = re.subn(
        pattern, lambda match: replacement, text, flags=re.MULTILINE
    )
    if count != 1:
        raise EnvironmentError(
            f"Init template must contain exactly one {field}; found {count}. "
            "Use a template with the projects/hello_world structure."
        )
    return rendered


def _relative(path: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError as error:
        raise EnvironmentError(
            f"Cannot create a relative project reference from {base} to {path}. "
            "Keep the workspace and dependencies on the same filesystem drive."
        ) from error


def _cmake_reference(path: Path, project: Path) -> str:
    relative = _relative(path, project)
    for character in ("\\", '"', "$", ";"):
        relative = relative.replace(character, "\\" + character)
    return '"${CMAKE_CURRENT_LIST_DIR}/' + relative + '"'


def _project_command(action: str, project_relative: str) -> str:
    # Names are restricted, but a configured projects_dir may contain spaces.
    path = (
        subprocess.list2cmdline([project_relative])
        if os.name == "nt"
        else shlex.quote(project_relative)
    )
    return f"python mosaico.py {action} --project {path}"


def _text(content: bytes) -> str:
    return content.decode("utf-8").replace("\r\n", "\n")


def _render(
    workspace: WorkspaceConfig, template: Path, project: Path, name: str
) -> dict[str, bytes]:
    files = {}
    for filename in TEMPLATE_FILES:
        source = template / filename
        if (
            not source.is_file()
            or source.is_symlink()
            or not _inside(source.resolve(), template)
        ):
            raise EnvironmentError(
                f"Init template file is missing or is not a regular local file: {source}"
            )
        files[filename] = source.read_bytes()

    # Shared workspace resources are referenced, never copied into the app.
    recovery = workspace.root / "components" / "esp_mosaico_app_recovery"
    system_update = workspace.root / "cmake" / "system_update.cmake"
    for required in (
        recovery / "CMakeLists.txt",
        system_update,
        workspace.root / "tools" / "prepare_system_update.py",
    ):
        if not required.is_file():
            raise EnvironmentError(f"Required workspace resource is missing: {required}")

    cmake = _text(files["CMakeLists.txt"])
    cmake = _replace_once(
        cmake, r"^project\(hello_world(?=[\s)])", f"project({name}",
        "project(hello_world ...) declaration",
    )
    cmake = _replace_once(
        cmake, r'set\(EXTRA_COMPONENT_DIRS\s+"[^"\n]*esp_mosaico_app_recovery"\s*\)',
        "set(EXTRA_COMPONENT_DIRS\n    " + _cmake_reference(recovery, project) + ")",
        "esp_mosaico_app_recovery component reference",
    )
    cmake = _replace_once(
        cmake, r'^include\([^\n)]*system_update\.cmake"?\)',
        "set(MOSAICO_ESP_IRIS_ROOT " + _cmake_reference(workspace.esp_iris_path, project) + ")\n"
        "include(" + _cmake_reference(system_update, project) + ")",
        "system_update.cmake include",
    )
    files["CMakeLists.txt"] = cmake.encode("utf-8")

    manifest = _text(files["main/idf_component.yml"])
    for dependency, component in (
        ("esp-mosaico-bsp", workspace.bsp_path / "components" / "esp-mosaico-bsp"),
        ("esp_iris", workspace.esp_iris_path / "components" / "esp_iris"),
    ):
        # Limit each edit to the named dependency's block, preserving all other
        # constraints and avoiding a runtime dependency on a YAML package.
        # Only lines indented below the dependency belong to its block.
        block_pattern = (
            r"^  " + re.escape(dependency)
            + r":[^\n]*\n(?:(?: {4}|\t)[^\n]*(?:\n|$)|\n)*"
        )
        blocks = list(re.finditer(block_pattern, manifest, flags=re.MULTILINE))
        if len(blocks) != 1:
            raise EnvironmentError(
                f"Init template must contain one {dependency} dependency block."
            )
        block = blocks[0].group()
        rewritten = _replace_once(
            block, r"^    override_path:[^\n]*",
            "    override_path: " + json.dumps(
                _relative(component, project / "main"), ensure_ascii=False
            ),
            f"{dependency} override_path",
        )
        match = blocks[0]
        manifest = manifest[:match.start()] + rewritten + manifest[match.end():]
    files["main/idf_component.yml"] = manifest.encode("utf-8")

    files["main/main.c"] = _replace_once(
        _text(files["main/main.c"]), r'^static const char \*TAG = "hello_world";',
        f'static const char *TAG = "{name}";', "Hello World log TAG",
    ).encode("utf-8")
    files["sdkconfig.application.defaults"] = _replace_once(
        _text(files["sdkconfig.application.defaults"]),
        r'^CONFIG_ESP_IRIS_USB_PRODUCT="[^"\n]*"',
        f'CONFIG_ESP_IRIS_USB_PRODUCT="ESP-Iris Mosaico {name}"', "USB product name",
    ).encode("utf-8")

    relative_project = project.relative_to(workspace.root).as_posix()
    readme = _text(files["README.md"])
    readme = _replace_once(
        readme, r"^# ESP-Mosaico Hello World$", f"# ESP-Mosaico {name}", "README title"
    )
    readme = readme.replace(
        "It is the reference normal\napplication: new projects should preserve its partition layout,",
        "It was created from the Hello World reference\napplication. Preserve its partition layout,",
    )
    for action in ("install", "system-update"):
        readme = _replace_once(
            readme, r"^python mosaico\.py " + action + r" --project projects/hello_world$",
            _project_command(action, relative_project), f"README {action} command",
        )
    readme += (
        "\nFor a blank or unverified device, initialize and verify retained Recovery\n"
        "from the workspace root before the first application install:\n\n"
        "```sh\npython mosaico.py recover\n```\n"
    )
    files["README.md"] = readme.encode("utf-8")
    return files


def _write_project(project: Path, root: Path, files: dict[str, bytes]) -> None:
    created_dirs = []
    created_files = []
    try:
        missing = []
        parent = project.parent
        while parent != root and not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                if not directory.is_dir():
                    raise
            else:
                created_dirs.append(directory)
        try:
            project.mkdir()  # Exclusive reservation; a concurrent init must fail.
        except FileExistsError as error:
            raise SelectionError(f"Project destination already exists: {project}") from error
        created_dirs.append(project)
        (project / "main").mkdir()
        created_dirs.append(project / "main")
        for filename, content in files.items():
            destination = project / filename
            with destination.open("xb") as stream:
                created_files.append(destination)
                stream.write(content)
    except (OSError, SelectionError, KeyboardInterrupt) as error:
        if isinstance(error, SelectionError):
            # Another creator owns the project and now needs its parent dirs.
            raise
        cleanup_errors = []
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError as cleanup_error:
                cleanup_errors.append(f"{path}: {cleanup_error}")
        for path in reversed(created_dirs):
            try:
                path.rmdir()  # Never recursively remove content we did not create.
            except OSError as cleanup_error:
                cleanup_errors.append(f"{path}: {cleanup_error}")
        raise OperationError(
            f"Could not create project {project}: {error or 'interrupted'}",
            details={"project": str(project), "cleanup_errors": cleanup_errors},
        ) from error


def initialize_project(
    workspace: WorkspaceConfig, name: str, *, dry_run: bool = False
) -> dict[str, Any]:
    """Validate, render and exclusively create a Hello World application."""

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name.lower() in _RESERVED_NAMES:
        raise SelectionError(
            "Project name must start with a letter and contain only ASCII letters, "
            "digits and underscores; Windows reserved names are not allowed."
        )
    # ESP-IDF stores the application name in a 32-byte, NUL-terminated field.
    if len(name) > 31:
        raise SelectionError("Project name must be at most 31 characters.")
    try:
        root = workspace.root.resolve()
        projects = workspace.projects_dir.resolve()
        if not _inside(projects, root):
            raise SelectionError("workspace.projects_dir must be a directory inside the workspace.")
        for parent in (projects, *projects.parents):
            if parent.exists():
                if not parent.is_dir():
                    raise EnvironmentError(f"Project parent is not a directory: {parent}")
                break
        project = projects / name
        if project.exists() or project.is_symlink():
            raise SelectionError(f"Project destination already exists: {project}")
        template = (workspace.init_template or root / "projects" / "hello_world").resolve()
        recovery = workspace.recovery_project.resolve()
        if template == recovery or _inside(template, recovery):
            raise SelectionError(
                "The retained Recovery firmware cannot be used as an application template."
            )
        files = _render(workspace, template, project, name)
    except (OSError, ValueError) as error:
        raise EnvironmentError(
            f"Could not read the init template or workspace resources: {error}"
        ) from error

    if not dry_run:
        _write_project(project, root, files)
    return {
        "command": "init",
        "status": "dry_run" if dry_run else "created",
        "name": name,
        "project": str(project),
        "template": str(template),
        "files": list(files),
        "install_command": _project_command("install", project.relative_to(root).as_posix()),
    }
