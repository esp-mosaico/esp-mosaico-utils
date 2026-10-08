from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from mosaico_cli.cli import build_parser
from mosaico_cli.app_commands import _engine_games, _iris_project
from mosaico_cli.errors import SelectionError


class GameCommandTests(unittest.TestCase):
    def test_iris_build_needs_only_the_game(self) -> None:
        arguments = build_parser().parse_args([
            "game", "build", "sky_hop", "--target", "iris",
        ])

        self.assertEqual(arguments.project_path, "sky_hop")
        self.assertEqual(arguments.target, "iris")

    def test_native_selection_uses_board_matrix_and_excludes_local_experiments(self) -> None:
        result = SimpleNamespace(returncode=0, stdout=json.dumps({"games": [
            {"name": "native_game", "path": "/games/native_game", "host": True, "boards": ["esp-mosaico"]},
            {"name": "host_game", "path": "/games/host_game", "host": True, "boards": []},
            {"name": "unfinished_dev", "path": "/games/unfinished_dev", "host": True, "boards": ["esp-mosaico"]},
        ]}), stderr="")
        with patch("mosaico_cli.app_commands.subprocess.run", return_value=result) as run:
            games = _engine_games(Path("/engine"), "native")
        self.assertEqual(set(games), {"native_game"})
        self.assertNotIn("--target", run.call_args.args[0])

    def test_iris_generation_preserves_legacy_project_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "tools/templates/blank_game"
            template.mkdir(parents=True)
            (template / "partitions.csv").write_text("# product layout\n")
            source = root / "engine/examples/native_game"
            (source / "main").mkdir(parents=True)
            (source / "main/CMakeLists.txt").write_text("idf_component_register()")
            legacy = root / "runs/raylib-iris/native_game"
            legacy.mkdir(parents=True)
            (legacy / "sdkconfig").write_text("legacy config\n")
            workspace = SimpleNamespace(tool_root=root / "tools", run_dir=root / "runs")
            with patch("mosaico_cli.app_commands._engine", return_value=root / "engine"), patch(
                    "mosaico_cli.app_commands._engine_games", return_value={"native_game": root / "engine/examples/native_game"}):
                project = _iris_project(workspace, "native_game")
            self.assertEqual(project, legacy / "project")
            self.assertEqual((legacy / "sdkconfig").read_text(), "legacy config\n")
            self.assertEqual((project / "partitions.csv").read_text(), "# product layout\n")
            self.assertIn("system_update", (project / "CMakeLists.txt").read_text().lower())

    def test_external_games_do_not_require_example_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "tools/templates/blank_game"
            template.mkdir(parents=True)
            (template / "partitions.csv").write_text("# product layout\n")
            workspace = SimpleNamespace(root=root, tool_root=root / "tools", run_dir=root / "runs", recovery_project=root / "recovery")
            projects = []
            for parent in ("user one", "user two"):
                source = root / parent / "my_game"
                (source / "main").mkdir(parents=True)
                (source / "CMakeLists.txt").write_text("project(my_game)")
                (source / "main/CMakeLists.txt").write_text("idf_component_register()")
                (source / "sdkconfig.defaults").write_text("CONFIG_ESP_MAIN_TASK_STACK_SIZE=24576\n")
                (source / "version.txt").write_text("0.2.3\n")
                before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
                with patch("mosaico_cli.app_commands._engine", return_value=root / "engine"), patch(
                        "mosaico_cli.app_commands._engine_games", side_effect=AssertionError("must not query examples")):
                    project = _iris_project(workspace, str(source))
                    self.assertEqual(_iris_project(workspace, str(source)), project)
                cmake = (project / "CMakeLists.txt").read_text()
                self.assertIn(source.as_posix(), cmake)
                self.assertIn("VERSION 0.2.3", cmake)
                self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()})
                projects.append(project)
            self.assertNotEqual(projects[0], projects[1])

    def test_missing_explicit_path_never_selects_a_same_named_example(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = SimpleNamespace(root=root, recovery_project=root / "recovery")
            with patch("mosaico_cli.app_commands._engine", return_value=root / "engine"), patch(
                    "mosaico_cli.app_commands._engine_games", side_effect=AssertionError("must not query examples")):
                with self.assertRaises(SelectionError):
                    _iris_project(workspace, str(root / "missing/sky_hop"))

    def test_build_no_longer_accepts_a_product_root(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args([
                "game", "build", "sky_hop", "--target", "iris",
                "--product-root", "/tmp/product",
            ])


if __name__ == "__main__":
    unittest.main()
