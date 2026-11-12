"""A new game must not inherit a complete example's identity or assets."""
import csv
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / "tools"))
from mosaico_cli.cli import main


@pytest.fixture
def workspace():
    # Generated references are relative to the real utils checkout. Windows CI
    # puts that checkout on D: and pytest's default temporary directory on C:.
    # Keep this workspace on the checkout's drive, as in a consuming workspace.
    with TemporaryDirectory(prefix=".blank-game-test-", dir=TOOLS.parent) as temporary:
        root = Path(temporary) / "workspace with spaces"
        root.mkdir()
        # Creation needs an initialized engine, but neither BSP nor an SDK install.
        engine = root / "engine"
        engine.mkdir()
        (engine / "idf_component.yml").touch()
        (engine / "CMakeLists.txt").touch()
        (root / ".mosaico.json").write_text(json.dumps({
            "schema_version": 2,
            "workspace": {"projects_dir": "projects"},
            "dependencies": {"bsp": "board", "raylib": "engine", "esp_iris": "iris"},
            "build": {"runner": "builtin"},
            "devices": [{"id": "esp-mosaico", "name": "ESP-Mosaico",
                         "target": "esp32s31", "status": "supported", "default": True}],
        }), encoding="utf-8")
        yield root


@pytest.mark.parametrize("action,options", [
    ("create", []), ("create", ["--template", "blank"]), ("new", []),
])
def test_blank_creation_uses_project_identity_without_example_assets(workspace, capsys, action, options):
    assert main(["--workspace", str(workspace), "game", action, "my_snake", *options, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    project = Path(result["project"])
    assert result["status"] == "created"
    assert "iris system-update" in result["install_command"]
    assert not (workspace / "board").exists()
    assert not (project / "assets_src").exists()
    assert not (project / "assets").exists()
    assert set(json.loads((project / "game.sim.json").read_text())["sources"]) == {
        "main/game_entry.c", "components/app_game/app_game.c", "components/app_game_runtime/app_game_runtime.c",
    }
    for name in result["files"]:
        text = (project / name).read_text()
        assert "shooter" not in text.lower(), name
        assert "blank_game" not in text, name
        assert "{{" not in text, name
        assert str(workspace) not in text, name
    assert '#define GAME_NAME "my_snake"' in (project / "components/app_game_runtime/private/game_config.h").read_text()
    assert 'project(my_snake VERSION' in (project / "CMakeLists.txt").read_text()
    assert 'ESP-Iris Mosaico my_snake' in (project / "sdkconfig.application.defaults").read_text()
    assert (project / "README.md").read_text().startswith("# my_snake\n")
    import yaml
    manifest = yaml.safe_load((project / "main/idf_component.yml").read_text())
    pin = json.loads((TOOLS / "raylib-toolchain.json").read_text())
    assert manifest["dependencies"][pin["component"]] == "==" + pin["version"]
    cmake = (project / "CMakeLists.txt").read_text()
    for variable, expected in (("MOSAICO_UTILS_ROOT", TOOLS.parent),
                               ("MOSAICO_BSP_ROOT", workspace / "board"),
                               ("RAYLIB_LITE_ENGINE_ROOT", workspace / "engine")):
        relative = re.search(r'set\(' + variable + r' "\$\{CMAKE_CURRENT_LIST_DIR\}/([^"\n]+)"\)', cmake).group(1)
        assert (project / relative).resolve() == expected.resolve()

    rows = [[part.strip() for part in row] for row in csv.reader(
        (project / "partitions.csv").read_text().splitlines()) if row and not row[0].startswith("#")]
    partitions = {name: [kind, sub, int(offset, 0), int(size, 0), flags]
                  for name, kind, sub, offset, size, flags in rows}
    contract = json.loads((TOOLS.parent / "esp-mosaico-vibe-mode/product_contract.json").read_text())
    for name, values in contract["immutable_layout"].items():
        assert partitions[name] == values
    assert set(partitions) == {*contract["immutable_layout"], "nvs", "main_app"}


def test_blank_dry_run_and_refusal_to_overwrite(workspace, capsys):
    arguments = ["--workspace", str(workspace), "game", "create", "my_game"]
    assert main([*arguments, "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    assert not (workspace / "projects").exists()
    assert main(arguments) == 0
    marker = workspace / "projects/my_game/components/app_game/app_game.c"
    marker.write_text("user game\n")
    assert main(arguments) != 0
    assert marker.read_text() == "user game\n"


@pytest.mark.parametrize("option,example", [
    ("shooter", "raylib_shooter"), ("sky-hop", "sky_hop"),
    ("tower-defense", "tower_defense"), ("last-zone", "last_zone_extraction"),
])
def test_example_selection_uses_registry_download(workspace, capsys, option, example, monkeypatch):
    source = workspace / "downloaded" / example
    (source / "main").mkdir(parents=True)
    (source / "CMakeLists.txt").write_text("project(" + example + " VERSION 1.0.0)\n")
    (source / "main/idf_component.yml").write_text("dependencies: {}\n")
    (source / "LICENSE").write_text("example license\n")
    calls = []

    def download(selected_workspace, name):
        calls.append(name)
        return source

    monkeypatch.setattr("mosaico_cli.registry_examples.ensure_example", download)
    assert main(["--workspace", str(workspace), "game", "create", "demo", "--template", option, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    project = Path(result["project"])
    assert calls == [example]
    assert "project(demo VERSION" in (project / "CMakeLists.txt").read_text()
    assert (project / "LICENSE").read_text() == "example license\n"
    assert not (workspace / "board").exists()


def test_example_dry_run_does_not_download(workspace, capsys, monkeypatch):
    monkeypatch.setattr("mosaico_cli.registry_examples.ensure_example", lambda *_: pytest.fail("dry run downloads"))
    assert main(["--workspace", str(workspace), "game", "create", "demo", "--template", "last-zone", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    assert not (workspace / "projects").exists()
