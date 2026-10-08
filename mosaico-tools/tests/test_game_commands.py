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

    def test_build_no_longer_accepts_a_product_root(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args([
                "game", "build", "sky_hop", "--target", "iris",
                "--product-root", "/tmp/product",
            ])


if __name__ == "__main__":
    unittest.main()
