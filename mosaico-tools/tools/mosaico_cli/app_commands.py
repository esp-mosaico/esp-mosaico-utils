"""Workspace application creation and preview using public dependency entry points."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

from .errors import EnvironmentError, SelectionError
from .project import resolve_project
from .scaffold import initialize_project

GAME_TEMPLATES = {"shooter": "raylib_shooter", "sky-hop": "sky_hop", "tower-defense": "tower_defense"}
DEFAULT_GAME_TEMPLATE = "blank"

IRIS_PROJECT_CMAKE = """cmake_minimum_required(VERSION 3.16)
set(RAYLIB_LITE_GAME {game})
include("{module}")
project({game} VERSION 1.0.0)
raylib_lite_iris_link_game_board()
include("${{MOSAICO_SYSTEM_UPDATE_CMAKE}}")
"""


def _engine(workspace, purpose):
    engine = workspace.raylib_path
    if engine is None or not (engine / "tools/game_cli.py").is_file():
        raise EnvironmentError(f"Initialize the configured Raylib Lite Engine dependency before {purpose}.")
    return engine


def _engine_games(engine, target):
    completed = subprocess.run(
        [sys.executable, str(engine / "tools/game_cli.py"), "list", "--json"],
        capture_output=True, text=True,
    )
    if completed.returncode:
        raise EnvironmentError(completed.stderr.strip() or "Engine game listing failed.")
    games = json.loads(completed.stdout)["games"]
    return {game["name"]: Path(game["path"]) for game in games
            if not game["name"].endswith("_dev")
            and (game.get("host", False) if target == "host" else game.get("boards", []))}


def _iris_project(workspace, selected):
    """Generate the ESP-Iris wrapper project for one native engine game."""
    engine = _engine(workspace, "an Iris build")
    games = _engine_games(engine, "native")
    name = Path(selected).name
    if name not in games:
        raise SelectionError(f"Not a native engine game: {selected}; choose one of {', '.join(sorted(games))}.")
    template = workspace.tool_root / "templates" / "blank_game"
    project = workspace.run_dir / "raylib-iris" / name / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "CMakeLists.txt").write_text(IRIS_PROJECT_CMAKE.format(
        game=name, module=(workspace.tool_root / "cmake/raylib_lite_iris_app.cmake").as_posix()))
    (project / "partitions.csv").write_bytes((template / "partitions.csv").read_bytes())
    return project


def add_commands(commands, project_commands):
    preview = project_commands.add_parser("sim", help="Preview a GSP application with its native PC backend")
    preview.set_defaults(command="sim", public_command="project sim")
    preview.add_argument("--project")
    preview.add_argument("--scene-only", action="store_true")
    mode = preview.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true")
    mode.add_argument("--interactive", action="store_true")
    preview.add_argument("--duration", type=float)
    preview.add_argument("--frames", type=int)
    preview.add_argument("--fps", type=int)
    preview.add_argument("--dump-ppm")
    game = commands.add_parser("game", help="Create blank games or BSP examples and use the Raylib Host simulator")
    actions = game.add_subparsers(dest="game_action", required=True)
    for name in ("create", "new"):
        create = actions.add_parser(name, help="Create a blank game or a complete BSP example")
        create.set_defaults(command="game", public_command="game " + name)
        create.add_argument("name")
        create.add_argument("--template", choices=(DEFAULT_GAME_TEMPLATE, *GAME_TEMPLATES),
                            default=DEFAULT_GAME_TEMPLATE, help="Game template (default: blank)")
        create.add_argument("--dry-run", action="store_true")
    for name in ("sim", "run", "build"):
        child = actions.add_parser(name)
        child.set_defaults(command="game", public_command="game " + name)
        child.add_argument("project_path", nargs="?")
        child.add_argument("--project")
        if name == "build":
            child.add_argument("--idf-path")
            child.add_argument("--target", choices=("native", "iris"), default="native",
                               help="native: build the project as is; iris: wrap an engine game as an ESP-Iris app")
        else:
            child.add_argument("--headless", action="store_true")
            child.add_argument("--frames", type=int, default=300)
            child.add_argument("--listen", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
            child.add_argument("--port", type=int, default=8460)
            child.add_argument("--scenario", "--replay", dest="replay")
            child.add_argument("--state-output")


def run(arguments, workspace):
    tools_root = workspace.recovery_project.parents[2] / "mosaico-tools"
    if arguments.command == "sim":
        project = resolve_project(workspace, arguments.project, Path.cwd())
        command = [sys.executable, str(tools_root / "tools/gsp-sim/run.py"),
                   "--project", str(project)]
        for flag in ("headless", "interactive", "scene_only"):
            if getattr(arguments, flag):
                command.append("--" + flag.replace("_", "-"))
        for flag in ("duration", "frames", "fps", "dump_ppm"):
            value = getattr(arguments, flag)
            if value is not None:
                command.extend(("--" + flag.replace("_", "-"), str(value)))
        return subprocess.call(command)

    if arguments.game_action in {"create", "new"}:
        template = (tools_root / "templates/blank_game/mosaico-template.json"
                    if arguments.template == DEFAULT_GAME_TEMPLATE else
                    workspace.bsp_path / "examples" / GAME_TEMPLATES[arguments.template] / "mosaico-template.json")
        if not template.is_file():
            owner = "utils" if arguments.template == DEFAULT_GAME_TEMPLATE else "BSP"
            raise EnvironmentError(f"Initialize the {owner} submodule containing the selected game template: " + str(template))
        engine = workspace.raylib_path
        if engine is None or not (engine / "cmake/mosaico_game_sdk.cmake").is_file():
            raise EnvironmentError("Initialize the configured Raylib Lite Engine dependency before creating a game.")
        result = initialize_project(replace(workspace, init_template=template), arguments.name, dry_run=arguments.dry_run)
        if arguments.json:
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"game: {result['status']}\nProject: {result['project']}\n{result['install_command']}")
        return 0

    if arguments.project and arguments.project_path:
        raise SelectionError("Use either the positional project or --project.")
    iris = arguments.game_action == "build" and arguments.target == "iris"
    selected = arguments.project or arguments.project_path
    if iris:
        if not selected:
            raise SelectionError("Specify an engine game for an Iris build.")
        project = _iris_project(workspace, selected)
    else:
        candidate = workspace.raylib_path / selected if workspace.raylib_path and selected else None
        required = "CMakeLists.txt" if arguments.game_action == "build" else "game.sim.json"
        project = (candidate.resolve() if candidate and not Path(selected).exists() and (candidate / required).is_file()
                   else resolve_project(workspace, selected, Path.cwd()))
    if arguments.game_action == "build":
        import os
        from .runtime import RunContext, build_application
        if arguments.idf_path:
            os.environ["IDF_PATH"] = str(Path(arguments.idf_path).expanduser().resolve())
        os.environ["RAYLIB_LITE_ENGINE_ROOT"] = str(workspace.raylib_path)
        os.environ["MOSAICO_UTILS_ROOT"] = str(workspace.tool_root.parent)
        os.environ["MOSAICO_BSP_ROOT"] = str(workspace.bsp_path)
        context = RunContext(workspace, "game-build", arguments.verbose, arguments.json)
        build_application(context, project)
        if iris:
            from .gateway import ensure_iris_tools
            from .runtime import resolve_idf_path, run_idf_target
            iris_python, _ = ensure_iris_tools(context)
            run_idf_target(context, idf_path=resolve_idf_path(workspace, project),
                           project=project, build_dir=project / "build",
                           target="system-update-bundle",
                           definitions={"ESP_IRIS_PYTHON": str(iris_python)}, timeout=900)
            context.status(f"system update bundle: {project / 'build' / (Path(selected).name + '-system-update.irisfw')}")
        return 0
    engine = workspace.raylib_path
    if engine is None or not (engine / "host/run_game.py").is_file():
        raise EnvironmentError("Initialize the configured Raylib Lite Engine dependency before simulation.")
    command = [sys.executable, str(engine / "host/run_game.py"), "--project", str(project),
               "--listen", arguments.listen, "--port", str(arguments.port)]
    if arguments.headless:
        command.extend(("--headless", "--frames", str(arguments.frames)))
    for name in ("replay", "state_output"):
        value = getattr(arguments, name)
        if value:
            command.extend(("--" + name.replace("_", "-"), value))
    return subprocess.call(command)
